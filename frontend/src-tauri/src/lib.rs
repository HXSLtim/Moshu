use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use tauri::{RunEvent, WebviewUrl, WebviewWindowBuilder};

/// localhost 资产服务端口（壳窗口载 http，插件经 asset_resolver 服务 frontendDist）。
const ASSET_PORT: u16 = 21_490;
/// 契约 B10：冷启 P95 2-3s，就绪超时 15s 留首次迁移余量。
const HEALTH_TIMEOUT_SECS: u64 = 15;
const HEALTH_POLL_MS: u64 = 300;
/// 契约 B11：崩溃重启 3 次/1s 起指数退避。
const SIDECAR_MAX_RESTARTS: u32 = 3;
/// 契约 B12：SIGTERM 后优雅关停等待窗（uvicorn 通常 <1s）。
const TERM_GRACE_MS: u64 = 5_000;

/// sidecar 子进程句柄；None=未启动/已放弃，退出清理与监护线程共用。
type SharedChild = Arc<Mutex<Option<Child>>>;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  // 生命周期状态在 Builder 外创建：setup 填充，退出回调消费。
  let shutdown = Arc::new(AtomicBool::new(false));
  let sidecar: SharedChild = Arc::new(Mutex::new(None));

  tauri::Builder::default()
    // http 资产服务形态：frontendDist 由 localhost 插件在 http://localhost:<port>
    // 下服务，窗口载该地址——避开 tauri:// 自定义协议对 http API 的跨域预检坑。
    .plugin(tauri_plugin_localhost::Builder::new(ASSET_PORT).build())
    // 深链最小集：nai:// scheme（注册配置在 tauri.conf.json plugins.deep-link）。
    .plugin(tauri_plugin_deep_link::init())
    .setup({
      let shutdown = shutdown.clone();
      let sidecar = sidecar.clone();
      move |app| {
        if cfg!(debug_assertions) {
          app.handle().plugin(
            tauri_plugin_log::Builder::default()
              .level(log::LevelFilter::Info)
              .build(),
          )?;
        }

        // 件4：壳随机分配空闲口，经 --port arg 传 sidecar（契约 B6/B7）。
        let port = alloc_port().ok_or("127.0.0.1 上无可用空闲端口")?;
        let backend = backend_dir()?;
        let child = spawn_sidecar(port, &backend)
          .map_err(|e| format!("sidecar 拉起失败：{e}"))?;
        *sidecar.lock().expect("sidecar 锁") = Some(child);

        // 件6：健康轮询 + 崩溃重启监护线程（判据=GET /api/health HTTP 200，
        // 契约 B9 明确勿按 body 字段值判）。
        {
          let shutdown = shutdown.clone();
          let sidecar = sidecar.clone();
          thread::spawn(move || supervise(port, shutdown, sidecar));
        }

        // 主窗口代码创建：端口先知，API 基址经 initialization_script 注入
        // （件5 消费点 mutator resolveApiBase），消除「页面先载、注入后到」竞态。
        let init_js = format!("window.__NAI_API_BASE__ = 'http://127.0.0.1:{port}/api';");
        let window = WebviewWindowBuilder::new(
          app,
          "main",
          WebviewUrl::External(format!("http://localhost:{ASSET_PORT}/index.html").parse()?),
        )
        .title("墨枢")
        .inner_size(1280.0, 800.0)
        .min_inner_size(960.0, 640.0)
        .resizable(true)
        .initialization_script(&init_js)
        .build()?;
        window.set_focus().ok();

        // 启动时聚焦主窗口（真正的单实例守卫=tauri-plugin-single-instance，P3 随更新通道再进）。
        Ok(())
      }
    })
    .build(tauri::generate_context!())
    .expect("error while building tauri application")
    .run({
      let shutdown = shutdown.clone();
      let sidecar = sidecar.clone();
      move |_app, event| {
        // 件6：退出清理 SIGTERM→5s→SIGKILL（契约 B12）。
        if let RunEvent::Exit = event {
          shutdown.store(true, Ordering::Relaxed);
          graceful_stop(&sidecar);
        }
      }
    });
}

/// 件4：绑定探测式随机端口分配（绑定后立即释放，与 uvicorn 绑定间存在理论竞窗，
/// 撞上时由监护重启循环兜底）。
fn alloc_port() -> Option<u16> {
  let listener = TcpListener::bind(("127.0.0.1", 0)).ok()?;
  listener.local_addr().ok().map(|a| a.port())
}

/// 开发树路径（CARGO_MANIFEST_DIR=frontend/src-tauri 回溯仓库根）；P3 打包时切换到资源目录。
fn backend_dir() -> Result<PathBuf, Box<dyn std::error::Error>> {
  let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../backend");
  Ok(dir.canonicalize()?)
}

/// 件3：壳拉起解释器+uvicorn（契约 B1/B2：入口=backend/.venv/bin/python，
/// cwd=backend/ 供 app 包相对导入；env 只注入不写文件，契约 B3/B15）。
fn spawn_sidecar(port: u16, backend: &std::path::Path) -> Result<Child, String> {
  let python = backend.join(".venv/bin/python");
  if !python.exists() {
    return Err(format!("sidecar 解释器不存在：{}", python.display()));
  }
  Command::new(&python)
    .args([
      "-m",
      "uvicorn",
      "app.main:app",
      "--host",
      "127.0.0.1",
      "--port",
      &port.to_string(),
    ])
    .current_dir(backend)
    // P1 spike：SECRET_KEY 每次启动临时生成（跨重启会话失效可接受），P2 首启引导持久化。
    .env("SECRET_KEY", secret_key().map_err(|e| e.to_string())?)
    // B13 两道并存之 env 覆盖道：默认值已加 21490 对，此处并入 dev 端口一并声明。
    .env(
      "ALLOWED_ORIGINS",
      format!(
        "http://localhost:{ASSET_PORT},http://127.0.0.1:{ASSET_PORT},http://localhost:3000"
      ),
    )
    .stdout(Stdio::inherit())
    .stderr(Stdio::inherit())
    .spawn()
    .map_err(|e| e.to_string())
}

/// P1 spike：/dev/urandom 32 字节 hex=64 字符，过 SECRET_KEY 占位黑名单校验。
fn secret_key() -> Result<String, std::io::Error> {
  let mut file = std::fs::File::open("/dev/urandom")?;
  let mut buf = [0u8; 32];
  file.read_exact(&mut buf)?;
  Ok(buf.iter().map(|b| format!("{b:02x}")).collect())
}

/// 件6：裸 TcpStream 单请求判 health 200（零新依赖，不引 HTTP 客户端）。
fn health_ok(port: u16) -> bool {
  let Ok(mut stream) = TcpStream::connect(("127.0.0.1", port)) else {
    return false;
  };
  let req = format!("GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n");
  if stream.write_all(req.as_bytes()).is_err() {
    return false;
  }
  let mut buf = [0u8; 32];
  match stream.read(&mut buf) {
    Ok(n) => buf[..n].starts_with(b"HTTP/1.1 200") || buf[..n].starts_with(b"HTTP/1.0 200"),
    Err(_) => false,
  }
}

fn wait_healthy(port: u16, shutdown: &AtomicBool) -> bool {
  let deadline = Instant::now() + Duration::from_secs(HEALTH_TIMEOUT_SECS);
  while Instant::now() < deadline {
    if shutdown.load(Ordering::Relaxed) {
      return false;
    }
    if health_ok(port) {
      return true;
    }
    thread::sleep(Duration::from_millis(HEALTH_POLL_MS));
  }
  false
}

fn child_exited(child: &SharedChild) -> bool {
  let mut guard = child.lock().expect("sidecar 锁");
  guard
    .as_mut()
    .map(|c| matches!(c.try_wait(), Ok(Some(_))))
    .unwrap_or(true)
}

/// 监护循环：健康即守、死则按 1s 起指数退避重启，超限放弃（前端走既有失败态，
/// 后续可加壳级错误窗，P3）。
fn supervise(port: u16, shutdown: Arc<AtomicBool>, sidecar: SharedChild) {
  let mut restarts: u32 = 0;
  let mut delay: u64 = 1;
  loop {
    let became_healthy = wait_healthy(port, &shutdown);
    if shutdown.load(Ordering::Relaxed) {
      return;
    }
    if became_healthy {
      log::info!("sidecar 就绪 @127.0.0.1:{port}");
      // 守到进程退出才进入重启分支。
      while !shutdown.load(Ordering::Relaxed) && !child_exited(&sidecar) {
        thread::sleep(Duration::from_millis(HEALTH_POLL_MS));
      }
    } else {
      log::warn!("sidecar {HEALTH_TIMEOUT_SECS}s 内未就绪");
    }
    if shutdown.load(Ordering::Relaxed) {
      return;
    }
    restarts += 1;
    if restarts > SIDECAR_MAX_RESTARTS {
      log::error!("sidecar 重启超限（{SIDECAR_MAX_RESTARTS} 次），放弃——前端按既有失败态提示");
      return;
    }
    log::warn!("sidecar 退出，{delay}s 后第 {restarts} 次重启");
    thread::sleep(Duration::from_secs(delay));
    delay *= 2;
    if shutdown.load(Ordering::Relaxed) {
      return;
    }
    match spawn_sidecar(port, &backend_dir().expect("backend 目录")) {
      Ok(child) => {
        *sidecar.lock().expect("sidecar 锁") = Some(child);
      }
      Err(e) => {
        log::error!("sidecar 重启拉起失败：{e}");
        return;
      }
    }
  }
}

/// 件6：SIGTERM→轮询 5s→SIGKILL（SQLite WAL 随连接关闭正常 checkpoint，契约 B12）。
fn graceful_stop(sidecar: &SharedChild) {
  let mut guard = sidecar.lock().expect("sidecar 锁");
  if let Some(child) = guard.as_mut() {
    let pid = child.id() as i32;
    unsafe {
      libc::kill(pid, libc::SIGTERM);
    }
    let deadline = Instant::now() + Duration::from_millis(TERM_GRACE_MS);
    while Instant::now() < deadline {
      if matches!(child.try_wait(), Ok(Some(_))) {
        return;
      }
      thread::sleep(Duration::from_millis(100));
    }
    let _ = child.kill();
    let _ = child.wait();
  }
}

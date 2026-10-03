use tauri::Manager;

/// localhost 资产服务端口（壳窗口与插件共用；与 next dev 的 3000 无关）。
const ASSET_PORT: u16 = 21_490;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    // http 资产服务形态：frontendDist 由 localhost 插件在 http://localhost:<port>
    // 下服务，窗口载该地址——避开 tauri:// 自定义协议对 http API 的跨域预检坑。
    .plugin(tauri_plugin_localhost::Builder::new(ASSET_PORT).build())
    // 深链最小集：nai:// scheme（注册配置在 tauri.conf.json plugins.deep-link）。
    .plugin(tauri_plugin_deep_link::init())
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }

      // 启动时聚焦主窗口（真正的单实例守卫=tauri-plugin-single-instance，P3 随更新通道再进）。
      if let Some(window) = app.get_webview_window("main") {
        let _ = window.set_focus();
      }

      // API 基址注入的运行时契约在 P1 件4（壳动态分配端口传 sidecar）定案后接线：
      // 前端侧消费点已就位（mutator resolveApiBase 读 window.__NAI_API_BASE__）。
      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while building tauri application");
}

window.__ModuleLoader__.load({
  id: 'dsh-nai-ui',
  factory: (require) => {
    var module = { exports: {} }
    var exports = module.exports
    Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' })

    var React = require('react')
    var h = React.createElement
    var useState = React.useState
    var useEffect = React.useEffect
    var Fragment = React.Fragment

    var CSS = [
      '.nai-ui-wrap{position:relative;display:inline-flex}',
      '.nai-ui-button{align-items:center;gap:6px;display:inline-flex;cursor:pointer;border:1px solid rgba(140,160,190,.25);border-radius:999px;background:rgba(140,160,190,.12);color:inherit;padding:3px 10px;font-size:12px;line-height:18px}',
      '.nai-ui-button:hover{border-color:rgba(140,160,190,.45);background:rgba(140,160,190,.2)}',
      '.nai-ui-panel{position:absolute;z-index:60;top:calc(100% + 8px);right:0;width:420px;max-width:88vw;max-height:560px;overflow:auto;border:1px solid rgba(140,160,190,.25);border-radius:12px;background:#171c26;color:#e8edf4;box-shadow:0 16px 48px rgba(0,0,0,.35);padding:14px}',
      '.nai-ui-panel--embedded{position:static;width:100%;max-width:820px;max-height:none;box-shadow:none;margin:16px auto}',
      '.nai-ui-title{font-size:14px;font-weight:600;margin:0 0 10px;display:flex;align-items:center;gap:8px}',
      '.nai-ui-section{margin:12px 0}',
      '.nai-ui-section-title{font-size:12px;font-weight:600;color:#9aa8bd;margin:0 0 6px}',
      '.nai-ui-novel{border:1px solid rgba(140,160,190,.18);border-radius:10px;padding:10px;margin:8px 0}',
      '.nai-ui-novel-title{font-size:13px;font-weight:600;margin:0 0 4px}',
      '.nai-ui-meta{font-size:12px;color:#9aa8bd}',
      '.nai-ui-actions{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}',
      '.nai-ui-action{cursor:pointer;border:1px solid rgba(140,160,190,.25);border-radius:8px;background:rgba(140,160,190,.1);color:inherit;padding:4px 8px;font-size:12px}',
      '.nai-ui-action:hover{background:rgba(140,160,190,.22)}',
      '.nai-ui-error{color:#ff9e9e;font-size:12px;white-space:pre-wrap}',
      '.nai-ui-empty{font-size:12px;color:#9aa8bd}',
      '.nai-ui-card{border:1px solid rgba(140,160,190,.2);border-radius:10px;background:rgba(20,25,34,.6);padding:10px;margin:4px 0}',
      '.nai-ui-card-title{font-size:13px;font-weight:600;margin:0 0 6px}',
      '.nai-ui-pre{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;line-height:1.5;white-space:pre-wrap;word-break:break-word;margin:0;max-height:360px;overflow:auto}',
      '.nai-ui-note{font-size:12px;color:#9aa8bd;padding:24px;text-align:center}',
      '.nai-ui-table{width:100%;border-collapse:collapse;font-size:12px}',
      '.nai-ui-table th,.nai-ui-table td{text-align:left;border-bottom:1px solid rgba(140,160,190,.15);padding:4px 6px}'
    ].join('\n')

    if (typeof document !== 'undefined') {
      var style = document.createElement('style')
      style.dataset.plugin = 'dsh-nai-ui'
      style.dataset.pluginCss = 'dsh-nai-ui/styles.css'
      style.textContent = CSS
      document.head.appendChild(style)
    }

    function textFromBlocks(blocks) {
      return (blocks || [])
        .map(function (block) { return block && block.type === 'text' ? block.text : '' })
        .join('\n')
    }

    function safeParse(text) {
      try { return JSON.parse(text) } catch { return null }
    }

    function capText(text, limit) {
      var maxChars = limit || 120000
      if (typeof text !== 'string') return text
      if (text.length <= maxChars) return text
      return text.slice(0, maxChars) + '\n\n……内容过长，已截断……'
    }

    function fetchJson(path, signal) {
      return fetch(path, { signal }).then(function (response) {
        if (!response.ok) throw new Error('HTTP ' + response.status)
        return response.json()
      })
    }

    function NaiPanel(props) {
      var embedded = !!props.embedded
      var [state, setState] = useState({ loading: true, health: null, novels: null, stats: null, error: null })

      useEffect(function () {
        var controller = new AbortController()
        Promise.all([
          fetchJson('/nai-api/health', controller.signal),
          fetchJson('/nai-api/novels?limit=100', controller.signal),
          fetchJson('/nai-api/novels/statistics', controller.signal)
        ]).then(function (results) {
          setState({ loading: false, health: results[0], novels: results[1], stats: results[2], error: null })
        }, function (error) {
          if (controller.signal.aborted) return
          setState({ loading: false, health: null, novels: null, stats: null, error: error.message || String(error) })
        })
        return function () { controller.abort() }
      }, [])

      var items = state.novels || []
      var statsByNovel = Object.create(null)
      if (Array.isArray(state.stats && state.stats.items)) {
        state.stats.items.forEach(function (item) { statsByNovel[item.novel_id] = item })
      }

      return h('div', { className: 'nai-ui-panel' + (embedded ? ' nai-ui-panel--embedded' : '') },
        h('p', { className: 'nai-ui-title' },
          'Nai 写作台',
          state.health
            ? h('span', { className: 'nai-ui-meta' }, '后端在线 · ' + state.health.app_name)
            : h('span', { className: 'nai-ui-meta' }, '后端未连接')
        ),
        state.error ? h('p', { className: 'nai-ui-error' }, state.error) : null,
        state.loading ? h('p', { className: 'nai-ui-empty' }, '正在读取小说列表…') : null,
        !state.loading && items.length === 0
          ? h('p', { className: 'nai-ui-empty' }, '当前账号还没有小说，可让 Agent 调用 nai_novel_create 创建。')
          : null,
        items.map(function (novel) {
          var stat = statsByNovel[novel.id]
          return h('div', { className: 'nai-ui-novel', key: novel.id },
            h('p', { className: 'nai-ui-novel-title' }, novel.title),
            h('p', { className: 'nai-ui-meta' },
              'ID ' + novel.id + ' · ' + (novel.genre || '未设置类型') + ' · ' +
              (stat ? stat.chapter_count + ' 章 / ' + stat.total_words + ' 字' : '统计不可用')
            ),
            h('div', { className: 'nai-ui-actions' },
              h('button', {
                type: 'button',
                className: 'nai-ui-action',
                onClick: function (event) {
                  event.stopPropagation()
                  props.send('打开小说《' + novel.title + '》（novel_id=' + novel.id + '）：读取设定、角色和章节摘要，告诉我当前写到哪一章。')
                }
              }, '打开并读进度'),
              h('button', {
                type: 'button',
                className: 'nai-ui-action',
                onClick: function (event) {
                  event.stopPropagation()
                  props.send('为小说《' + novel.title + '》（novel_id=' + novel.id + '）生成下一章候选。先读最新章节和 Story Bible 上下文，生成后只展示候选，不要直接保存。')
                }
              }, '生成下一章候选')
            )
          )
        })
      )
    }

    function NaiHeaderControl(props) {
      var preset = props.useSessions(function (state) {
        return state.byId[props.sessionId] && state.byId[props.sessionId].agentPreset
      })
      var [open, setOpen] = useState(false)

      if (preset !== 'nai-author') return null

      return h('span', { className: 'nai-ui-wrap' },
        h('button', {
          type: 'button',
          className: 'nai-ui-button',
          'aria-label': '打开 Nai 写作台',
          title: '打开 Nai 写作台',
          onClick: function () { setOpen(function (value) { return !value }) }
        }, 'Nai 写作台'),
        open ? h(NaiPanel, { send: props.send, embedded: false }) : null
      )
    }

    function NaiView(props) {
      var preset = props.useSessions(function (state) {
        return state.byId[props.sessionId] && state.byId[props.sessionId].agentPreset
      })

      if (preset !== 'nai-author') {
        return h('div', { className: 'nai-ui-note' },
          '当前会话未使用 nai-author preset。新建会话时选择「Nai 作者」，这里会展示 Nai 写作台。'
        )
      }

      return h(NaiPanel, { send: props.send, embedded: true })
    }

    function NaiToolCard(props) {
      var block = props.block
      var toolName = props.toolName || (block && block.name) || 'nai'

      if (!block) return null
      if (!('kind' in block) || block.kind !== 'tool-result') {
        return h('div', { className: 'nai-ui-card' },
          h('p', { className: 'nai-ui-card-title' }, 'Nai · 正在执行 ' + toolName),
          h('p', { className: 'nai-ui-meta' }, '等待 Nai 后端返回……')
        )
      }

      var text = textFromBlocks(block.content)
      var parsed = safeParse(text)
      var body = null

      if (toolName === 'nai_generation_generate' && parsed && typeof parsed.final_content === 'string') {
        body = h(Fragment, null,
          h('p', { className: 'nai-ui-meta' },
            '章节 ' + parsed.chapter + ' · 约 ' + parsed.final_content.length + ' 字符 · ' +
            '一致性：' + (parsed.final_consistency && parsed.final_consistency.status)
          ),
          h('pre', { className: 'nai-ui-pre' }, capText(parsed.final_content))
        )
      } else if (toolName === 'nai_chapters_list' && parsed && Array.isArray(parsed.items)) {
        body = h('table', { className: 'nai-ui-table' },
          h('thead', null,
            h('tr', null,
              h('th', null, '章号'),
              h('th', null, '标题'),
              h('th', null, '字数'),
              h('th', null, '版本')
            )
          ),
          h('tbody', null,
            parsed.items.map(function (chapter) {
              return h('tr', { key: chapter.id },
                h('td', null, chapter.chapter_number),
                h('td', null, chapter.title),
                h('td', null, chapter.word_count),
                h('td', null, chapter.version)
              )
            })
          )
        )
      } else if (parsed) {
        body = h('pre', { className: 'nai-ui-pre' }, capText(JSON.stringify(parsed, null, 2)))
      } else {
        body = h('pre', { className: 'nai-ui-pre' }, capText(text))
      }

      return h('div', { className: 'nai-ui-card' },
        h('p', { className: 'nai-ui-card-title' }, toolName),
        body
      )
    }

    function makeSend(ctx, sessionId) {
      var binding = ctx.sessions.binding(sessionId)
      return {
        send: function (text) {
          if (!binding || !binding.session) return Promise.resolve(null)
          return binding.session.prompt([{ type: 'text', text }], 'queue')
        }
      }
    }

    function apply(ctx) {
      ctx.slots.inject('conversation.session.header.actions', function () {
        return ctx.slots.register({
          name: 'conversation.session.header.actions',
          id: 'nai-header',
          order: 10,
          inject: function (sessionId) { return makeSend(ctx, sessionId) }
        }, NaiHeaderControl)
      })

      ctx.slots.inject('conversation.view', function () {
        return ctx.slots.register({
          name: 'conversation.view',
          id: 'nai',
          order: 15,
          label: function () { return 'Nai 写作台' },
          inject: function (sessionId) { return makeSend(ctx, sessionId) }
        }, NaiView)
      })

      ctx.slots.inject('tool.call.toolview', function* () {
        var keys = [
          'nai_novels_list',
          'nai_novel_get',
          'nai_characters_list',
          'nai_story_facts_list',
          'nai_story_events_list',
          'nai_chapters_list',
          'nai_chapter_get',
          'nai_chapter_create_next',
          'nai_chapter_update',
          'nai_generation_generate'
        ]
        for (var index = 0; index < keys.length; index += 1) {
          yield ctx.slots.register({
            name: 'tool.call.toolview',
            key: keys[index]
          }, NaiToolCard)
        }
      })
    }

    exports.apply = apply
    exports.inject = ['slots', 'sessions']
    return module.exports
  }
})

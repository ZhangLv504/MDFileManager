/* MDFileManager 前端：卡片入口 → 目录详情页 → 文档页 的三级导航。
 * 纯静态 JS，通过 Fetch 调用后端 JSON API，无任何构建步骤。
 * 渲染链：marked（含公式扩展）→ DOMPurify 净化 → Vue v-html → highlight.js / KaTeX 装饰。 */
(function () {
  'use strict';

  var parseMarkdown = (function () {
    if (window.marked && typeof window.marked.parse === 'function') {
      return window.marked.parse.bind(window.marked);
    }
    if (typeof window.marked === 'function') {
      return window.marked;
    }
    return function () { return '<p>Markdown 解析库未加载</p>'; };
  })();

  if (window.marked && typeof window.marked.setOptions === 'function') {
    window.marked.setOptions({ gfm: true, breaks: false });
  }

  var mathRenderer = null;
  if (window.MDFMMath && window.marked && window.katex) {
    mathRenderer = window.MDFMMath.install(window.marked, window.katex);
  }

  function renderMarkdown(source) {
    if (mathRenderer) mathRenderer.reset();
    var raw = parseMarkdown(source || '');
    return window.DOMPurify ? window.DOMPurify.sanitize(raw) : raw;
  }

  // 目录（TOC）最多收录的标题数量，避免超长文档拖慢渲染。
  var MAX_OUTLINE_ITEMS = 300;

  function slugifyHeading(text) {
    return String(text)
      .trim()
      .toLowerCase()
      .replace(/[\s\u3000]+/g, '-')
      .replace(/[^\w\u4e00-\u9fa5-]/g, '')
      .replace(/-{2,}/g, '-')
      .replace(/^-+|-+$/g, '');
  }

  /* 给渲染后的每个标题补上稳定 id，并抽取目录条目。
   * marked v12 起不再生成 heading id，这里统一补，保证目录跳转与高亮可用。
   * 同时按标题层级算出 parentId / hasChildren，供目录逐级折叠。
   * 返回 { html, headings: [{ id, level, depth, text, parentId, hasChildren }] }。 */
  function buildOutline(html) {
    var holder = document.createElement('div');
    holder.innerHTML = html || '';
    var nodes = holder.querySelectorAll('h1, h2, h3, h4, h5, h6');
    var used = Object.create(null);
    var headings = [];
    var stack = [];
    Array.prototype.forEach.call(nodes, function (node) {
      if (headings.length >= MAX_OUTLINE_ITEMS) return;
      var text = (node.textContent || '').replace(/\s+/g, ' ').trim();
      if (!text) return;
      var base = slugifyHeading(text) || 'section';
      var id = base;
      var seq = 2;
      while (used[id]) { id = base + '-' + seq; seq += 1; }
      used[id] = true;
      node.setAttribute('id', id);
      var level = Number(node.tagName.charAt(1));
      // 维护标题栈：弹出层级 >= 当前标题的节点，栈顶就是父标题。
      while (stack.length && stack[stack.length - 1].level >= level) stack.pop();
      var parentId = stack.length ? stack[stack.length - 1].id : '';
      stack.push({ level: level, id: id });
      headings.push({
        id: id, level: level, depth: 0, text: text,
        parentId: parentId, hasChildren: false
      });
    });
    if (headings.length) {
      var byId = Object.create(null);
      headings.forEach(function (item) { byId[item.id] = item; });
      headings.forEach(function (item) {
        if (item.parentId && byId[item.parentId]) byId[item.parentId].hasChildren = true;
      });
      var minLevel = headings.reduce(function (low, item) {
        return item.level < low ? item.level : low;
      }, 6);
      headings.forEach(function (item) {
        // 层级归一化：最浅标题作为根，最多缩进 3 级。
        item.depth = Math.min(Math.max(item.level - minLevel, 0), 3);
      });
    }
    return { html: holder.innerHTML, headings: headings };
  }

  function readTocVisible() {
    try {
      var saved = window.localStorage.getItem('mdfm:toc-visible');
      return saved === null ? true : saved === '1';
    } catch (error) {
      return true;
    }
  }

  function saveTocVisible(visible) {
    try { window.localStorage.setItem('mdfm:toc-visible', visible ? '1' : '0'); } catch (error) { /* 隐私模式忽略 */ }
  }

  function highlightAll() {
    if (!window.hljs) return;
    document.querySelectorAll('.markdown-body pre code').forEach(function (block) {
      if (block.getAttribute('data-highlighted') === 'yes') return;
      try { window.hljs.highlightElement(block); } catch (error) { /* 保持原文 */ }
    });
  }

  function decorate() {
    highlightAll();
    if (!mathRenderer) return;
    document.querySelectorAll('.markdown-body').forEach(function (root) {
      mathRenderer.renderInto(root);
    });
  }

  function encodePath(path) {
    return String(path).split('/').map(encodeURIComponent).join('/');
  }

  function setHash(prefix, path) {
    var suffix = path ? '#/' + prefix + '/' + encodeURIComponent(path) : window.location.pathname;
    try { window.history.replaceState(null, '', suffix); } catch (error) { /* 忽略 */ }
  }

  function sortNodes(nodes) {
    return (nodes || []).slice().sort(function (a, b) {
      if (a.type !== b.type) return a.type === 'dir' ? -1 : 1;
      return a.name.localeCompare(b.name, 'zh-CN');
    });
  }

  function countFiles(nodes) {
    return (nodes || []).reduce(function (total, node) {
      return total + (node.type === 'file' ? 1 : countFiles(node.children));
    }, 0);
  }

  function findNodeByPath(nodes, path) {
    for (var i = 0; i < (nodes || []).length; i += 1) {
      if (nodes[i].path === path) return nodes[i];
      var found = findNodeByPath(nodes[i].children, path);
      if (found) return found;
    }
    return null;
  }

  function readFileAsText(file) {
    return new Promise(function (resolve, reject) {
      if (typeof file.text === 'function') {
        file.text().then(resolve, reject);
        return;
      }
      var reader = new FileReader();
      reader.onload = function () { resolve(String(reader.result || '')); };
      reader.onerror = function () { reject(reader.error || new Error('读取文件失败')); };
      reader.readAsText(file, 'UTF-8');
    });
  }

  async function api(method, url, body) {
    var options = { method: method, headers: {} };
    if (body !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    var response = await fetch(url, options);
    var payload = null;
    try { payload = await response.json(); } catch (error) { payload = null; }
    if (!response.ok) {
      var detail = payload && payload.detail ? payload.detail : ('请求失败（HTTP ' + response.status + '）');
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return payload;
  }

  var app = Vue.createApp({
    data: function () {
      return {
        tree: [],
        activeDirPath: '',
        selectedDir: '',
        currentPath: '',
        content: '',
        original: '',
        editing: false,
        saving: false,
        // 左侧文档目录：默认展开，用户收起后的选择记在 localStorage。
        showToc: readTocVisible(),
        activeHeading: '',
        // 被折叠的标题 id 集合：默认全部展开，只记录用户主动折叠的节点。
        collapsedHeadings: {},
        tocScrollTick: false,
        backendOk: false,
        notice: null,
        showNew: false,
        newKind: 'dir',
        newName: '',
        contextMenu: null,
        showRename: false,
        renameName: '',
        renameTarget: { path: '', name: '', type: 'dir' },
        showMove: false,
        moveSource: { path: '', name: '', type: 'dir' },
        moveTarget: '',
        draggingPath: '',
        dropTarget: '',
        showDescription: false,
        descriptionText: '',
        descriptionTarget: '',
        showTrash: false,
        trashItems: [],
        trashCount: 0,
        trashBusy: false,
        showHistory: false,
        historyPath: '',
        historyVersions: [],
        selectedVersion: '',
        versionContent: '',
        versionSame: null,
        historyBusy: false,
        historyTab: 'source',
        diffBase: 'current',
        diffLines: [],
        diffStats: null,
        showRestoreLocation: false,
        restoreSource: { id: '', name: '', type: 'file', original_path: '' },
        restoreTarget: '',
        searchQuery: '',
        searchBusy: false,
        showSearch: false,
        searchResult: { query: '', count: 0, scanned: 0, results: [], truncated: false },
        showImport: false,
        importTarget: '',
        importFiles: [],
        importIgnored: 0,
        importKilobytes: 0,
        importOverwrite: false,
        importBusy: false,
        importResult: null,
        noticeTimer: null,
        keyHandler: null,
        hashHandler: null,
        docClickHandler: null
      };
    },

    computed: {
      renderedDoc: function () { return buildOutline(renderMarkdown(this.content)); },
      renderedHtml: function () { return this.renderedDoc.html; },
      docOutline: function () { return this.renderedDoc.headings; },
      // 折叠后实际可见的目录条目：父级折叠时整棵子树都跳过。
      visibleOutline: function () {
        var collapsed = this.collapsedHeadings;
        var hidden = Object.create(null);
        var visible = [];
        this.docOutline.forEach(function (item) {
          if (item.parentId && hidden[item.parentId]) {
            hidden[item.id] = true;
            return;
          }
          visible.push(item);
          if (collapsed[item.id]) hidden[item.id] = true;
        });
        return visible;
      },
      visibleHeadingIds: function () {
        var ids = Object.create(null);
        this.visibleOutline.forEach(function (item) { ids[item.id] = true; });
        return ids;
      },
      headingById: function () {
        var map = Object.create(null);
        this.docOutline.forEach(function (item) { map[item.id] = item; });
        return map;
      },
      // 可折叠（有子标题）的条目数量，为 0 时隐藏「全部折叠/展开」按钮。
      collapsibleCount: function () {
        return this.docOutline.filter(function (item) { return item.hasChildren; }).length;
      },
      allCollapsed: function () {
        var list = this.docOutline.filter(function (item) { return item.hasChildren; });
        if (!list.length) return false;
        return list.every(function (item) { return !!this.collapsedHeadings[item.id]; }, this);
      },
      dirty: function () { return this.content !== this.original; },
      docCount: function () { return countFiles(this.tree); },
      topCards: function () {
        return this.tree.filter(function (node) { return node.type === 'dir'; })
          .map(function (dir) {
            return {
              name: dir.name,
              path: dir.path,
              description: (dir.description || '').trim(),
              total: countFiles(dir.children),
              node: dir
            };
          });
      },
      activeDirNode: function () {
        return this.activeDirPath ? findNodeByPath(this.tree, this.activeDirPath) : null;
      },
      activeDescription: function () {
        return this.activeDirNode ? (this.activeDirNode.description || '').trim() : '';
      },
      activeChildren: function () {
        return this.activeDirNode ? sortNodes(this.activeDirNode.children) : [];
      },
      activeDirs: function () {
        return this.activeChildren.filter(function (node) { return node.type === 'dir'; })
          .map(function (node) {
            return {
              name: node.name, path: node.path, type: 'dir',
              description: node.description || '', total: countFiles(node.children)
            };
          });
      },
      activeFiles: function () {
        return this.activeChildren.filter(function (node) { return node.type === 'file'; });
      },
      breadcrumbs: function () {
        if (!this.activeDirPath) return [];
        var parts = this.activeDirPath.split('/');
        var acc = [];
        return parts.map(function (name) {
          acc.push(name);
          return { name: name, path: acc.join('/') };
        });
      },
      latestVersionNumber: function () {
        return this.historyVersions.length ? this.historyVersions[0].version : 0;
      },
      selectedVersionNumber: function () {
        var id = this.selectedVersion;
        var found = this.historyVersions.find(function (item) { return item.id === id; });
        return found ? found.version : 0;
      },
      restoreOptions: function () {
        if (this.restoreSource.type === 'file') return this.allDirs;
        return [{ name: '文档库（顶层）', path: '', depth: -1 }].concat(this.allDirs);
      },
      searchScope: function () {
        if (this.activeDirPath) return this.activeDirPath;
        if (this.currentPath) {
          var index = this.currentPath.lastIndexOf('/');
          return index > 0 ? this.currentPath.slice(0, index) : '';
        }
        return '';
      },
      searchScopeLabel: function () {
        return this.searchScope ? this.searchScope + '（含子目录）' : '整个文档库';
      },
      searchPlaceholder: function () {
        return '搜索 ' + (this.searchScope || '整个文档库') + ' 下的文档…';
      },
      importPreview: function () {
        return this.importFiles.slice(0, 8).map(function (item) {
          return { path: item.path };
        });
      },
      parentDirPath: function () {
        if (!this.activeDirPath) return '';
        var index = this.activeDirPath.lastIndexOf('/');
        return index > 0 ? this.activeDirPath.slice(0, index) : '';
      },
      allDirs: function () {
        var result = [];
        var walk = function (nodes, depth) {
          sortNodes(nodes).forEach(function (node) {
            if (node.type !== 'dir') return;
            result.push({
              name: new Array(depth + 1).join('　') + node.name,
              path: node.path,
              depth: depth
            });
            walk(node.children, depth + 1);
          });
        };
        walk(this.tree, 0);
        return result;
      },
      moveOptions: function () {
        var source = this.moveSource;
        if (!source.path) return [];
        var prefix = source.path + '/';
        var options = this.allDirs.filter(function (item) {
          return item.path !== source.path && item.path.indexOf(prefix) !== 0;
        });
        if (source.type === 'file') return options;
        return [{ name: '文档库（顶层）', path: '', depth: -1 }].concat(options);
      },
      newLocation: function () {
        return this.selectedDir ? this.selectedDir + '/' : 'data/（顶层）';
      },
      newPlaceholder: function () {
        return this.newKind === 'dir' ? '例如 前端笔记' : '例如 渲染说明.md';
      },
      newHint: function () {
        if (!this.selectedDir) {
          return '未选中目录时只能创建顶层目录。单击卡片或目录页里的文件夹可选中目录。';
        }
        return this.newKind === 'dir'
          ? '将在选中目录下创建子目录，创建后会自动选中新目录。'
          : '文件名可省略 .md（自动补全）；同名保存为覆盖更新。';
      }
    },

    watch: {
      renderedHtml: function () {
        this.activeHeading = '';
        Vue.nextTick(decorate);
      },
      editing: function (isEditing) {
        var self = this;
        Vue.nextTick(decorate);
        if (!isEditing) {
          // 从编辑切回阅读时回到顶部，目录高亮重新按视口计算。
          this.activeHeading = '';
          Vue.nextTick(function () {
            var container = self.$refs.viewerScroll;
            if (container) container.scrollTop = 0;
          });
        }
      },
      currentPath: function () {
        if (this.showHistory && this.currentPath !== this.historyPath) {
          this.showHistory = false;
        }
      },
      content: function () {
        if (this.selectedVersion && this.versionContent !== '') {
          this.versionSame = this.versionContent === this.content;
        }
        if (this.showHistory && this.historyTab === 'diff' && this.diffBase === 'current') {
          this.loadDiff();
        }
      },
      diffBase: function () {
        if (this.showHistory && this.historyTab === 'diff') this.loadDiff();
      }
    },

    mounted: function () {
      var self = this;
      this.keyHandler = function (event) {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
          event.preventDefault();
          self.saveDoc();
        }
      };
      this.hashHandler = function () { self.openFromHash(); };
      this.docClickHandler = function () { self.closeContextMenu(); };
      window.addEventListener('keydown', this.keyHandler);
      window.addEventListener('hashchange', this.hashHandler);
      document.addEventListener('click', this.docClickHandler);
      this.checkHealth();
      this.refreshTrashCount();
      this.refreshTree().then(function () { self.openFromHash(); });
    },

    beforeUnmount: function () {
      window.removeEventListener('keydown', this.keyHandler);
      window.removeEventListener('hashchange', this.hashHandler);
      document.removeEventListener('click', this.docClickHandler);
      clearTimeout(this.noticeTimer);
    },

    methods: {
      notify: function (text, type) {
        var self = this;
        this.notice = { text: text, type: type || 'info' };
        clearTimeout(this.noticeTimer);
        this.noticeTimer = setTimeout(function () { self.notice = null; }, 4000);
      },

      checkHealth: async function () {
        try {
          var health = await api('GET', '/api/health');
          this.backendOk = !!health && health.status === 'ok';
        } catch (error) {
          this.backendOk = false;
          this.notify('后端连接失败：' + error.message, 'error');
        }
      },

      refreshTree: async function () {
        try {
          var data = await api('GET', '/api/tree');
          this.tree = data.tree || [];
        } catch (error) {
          this.notify('目录加载失败：' + error.message, 'error');
        }
      },

      refreshTrashCount: async function () {
        try {
          var data = await api('GET', '/api/trash');
          this.trashCount = data.count || 0;
        } catch (error) {
          this.trashCount = 0;
        }
      },

      loadTrash: async function () {
        try {
          var data = await api('GET', '/api/trash');
          this.trashItems = data.items || [];
          this.trashCount = data.count || 0;
        } catch (error) {
          this.notify('回收站加载失败：' + error.message, 'error');
        }
      },

      openTrash: async function () {
        this.showTrash = true;
        await this.loadTrash();
      },

      restoreTrash: async function (itemId) {
        if (this.trashBusy) return;
        this.trashBusy = true;
        try {
          var result = await api('POST', '/api/trash/restore', { id: itemId });
          this.notify('已还原到 ' + result.path, 'success');
          await this.loadTrash();
          await this.refreshTree();
        } catch (error) {
          this.notify('还原失败：' + error.message, 'error');
        } finally {
          this.trashBusy = false;
        }
      },

      purgeTrash: async function (itemId) {
        if (this.trashBusy) return;
        if (!window.confirm('彻底删除这条回收站记录？此操作不可恢复。')) return;
        this.trashBusy = true;
        try {
          await api('DELETE', '/api/trash/' + encodeURIComponent(itemId));
          await this.loadTrash();
          this.notify('已彻底删除', 'success');
        } catch (error) {
          this.notify('彻底删除失败：' + error.message, 'error');
        } finally {
          this.trashBusy = false;
        }
      },

      emptyTrash: async function () {
        if (this.trashBusy) return;
        if (!window.confirm('确定清空回收站吗？所有条目将被永久删除，不可恢复。')) return;
        this.trashBusy = true;
        try {
          var result = await api('DELETE', '/api/trash');
          await this.loadTrash();
          this.notify('回收站已清空（' + result.purged + ' 项）', 'success');
        } catch (error) {
          this.notify('清空回收站失败：' + error.message, 'error');
        } finally {
          this.trashBusy = false;
        }
      },

      openRestoreLocation: function (item) {
        this.restoreSource = {
          id: item.id, name: item.name, type: item.type,
          original_path: item.original_path
        };
        var index = String(item.original_path || '').lastIndexOf('/');
        this.restoreTarget = index > 0
          ? String(item.original_path).slice(0, index) : '';
        var options = this.restoreOptions;
        var target = this.restoreTarget;
        if (!options.some(function (option) { return option.path === target; })) {
          this.restoreTarget = options.length ? options[0].path : '';
        }
        this.showRestoreLocation = true;
      },

      submitRestoreLocation: async function () {
        if (this.trashBusy || !this.restoreOptions.length) return;
        this.trashBusy = true;
        try {
          var result = await api('POST', '/api/trash/restore',
            { id: this.restoreSource.id, target_dir: this.restoreTarget });
          this.showRestoreLocation = false;
          await this.loadTrash();
          await this.refreshTree();
          this.notify('已还原到 ' + result.path
            + (result.relocated ? '（历史一并迁移）' : ''), 'success');
        } catch (error) {
          this.notify('还原失败：' + error.message, 'error');
        } finally {
          this.trashBusy = false;
        }
      },

      runSearch: async function () {
        var query = this.searchQuery.trim();
        if (!query) { this.notify('请输入搜索关键词', 'error'); return; }
        this.searchBusy = true;
        try {
          var url = '/api/search' + '?q=' + encodeURIComponent(query)
            + '&dir=' + encodeURIComponent(this.searchScope) + '&mode=both';
          this.searchResult = await api('GET', url);
          this.showSearch = true;
        } catch (error) {
          this.notify('搜索失败：' + error.message, 'error');
        } finally {
          this.searchBusy = false;
        }
      },

      highlightParts: function (text) {
        var value = String(text || '');
        var needle = String(this.searchResult.query || this.searchQuery || '').toLowerCase();
        if (!needle || !value) return [{ text: value, hit: false }];
        var lower = value.toLowerCase();
        var parts = [];
        var cursor = 0;
        while (cursor < value.length) {
          var at = lower.indexOf(needle, cursor);
          if (at < 0) {
            parts.push({ text: value.slice(cursor), hit: false });
            break;
          }
          if (at > cursor) parts.push({ text: value.slice(cursor, at), hit: false });
          parts.push({ text: value.slice(at, at + needle.length), hit: true });
          cursor = at + needle.length;
        }
        return parts.length ? parts : [{ text: value, hit: false }];
      },

      openSearchResult: function (item) {
        this.showSearch = false;
        if (item.dir) this.activeDirPath = item.dir;
        this.selectDoc(item.path);
      },

      openImport: function () {
        this.importTarget = this.selectedDir || this.searchScope
          || (this.allDirs.length ? this.allDirs[0].path : '');
        this.importFiles = [];
        this.importIgnored = 0;
        this.importKilobytes = 0;
        this.importOverwrite = false;
        this.importResult = null;
        this.showImport = true;
        var self = this;
        Vue.nextTick(function () {
          if (self.$refs.importPickFirst) self.$refs.importPickFirst.focus();
        });
      },

      pickImportFiles: function () {
        if (this.$refs.importFileInput) this.$refs.importFileInput.click();
      },

      pickImportFolder: function () {
        if (this.$refs.importDirInput) this.$refs.importDirInput.click();
      },

      onImportPicked: function (event) {
        var input = event.target;
        var picked = Array.prototype.slice.call(input.files || []);
        var kept = [];
        var ignored = 0;
        picked.forEach(function (file) {
          var relative = file.webkitRelativePath || file.name || '';
          if (!/\.md$/i.test(relative)) { ignored += 1; return; }
          kept.push({ file: file, path: relative });
        });
        this.importIgnored = ignored;
        this.importResult = null;
        var self = this;
        Promise.all(kept.map(function (item) {
          return readFileAsText(item.file).then(function (text) {
            return { path: item.path, content: text };
          });
        })).then(function (list) {
          self.importFiles = list;
          var characters = list.reduce(function (total, item) {
            return total + item.content.length;
          }, 0);
          self.importKilobytes = Math.round(characters / 1024 * 10) / 10;
        }).catch(function (error) {
          self.notify('读取本地文件失败：' + (error && error.message ? error.message : error), 'error');
        });
        try { input.value = ''; } catch (error) { /* 允许重复选择同一文件 */ }
      },

      submitImport: async function () {
        if (!this.importFiles.length || !this.importTarget || this.importBusy) return;
        this.importBusy = true;
        try {
          var result = await api('POST', '/api/import', {
            target_dir: this.importTarget,
            files: this.importFiles,
            overwrite: this.importOverwrite
          });
          this.importResult = result;
          this.importFiles = [];
          this.importIgnored = 0;
          this.importKilobytes = 0;
          await this.refreshTree();
          this.notify('导入完成：成功 ' + result.count + '，跳过 ' + result.skipped_count
            + '，失败 ' + result.error_count, result.error_count ? 'error' : 'success');
        } catch (error) {
          this.notify('导入失败：' + error.message, 'error');
        } finally {
          this.importBusy = false;
        }
      },

      versionLabel: function (action) {
        if (action === 'created') return '创建';
        if (action === 'restore') return '还原';
        return '保存';
      },

      openHistory: async function () {
        if (!this.currentPath) return;
        this.historyPath = this.currentPath;
        this.selectedVersion = '';
        this.versionContent = '';
        this.versionSame = null;
        this.historyTab = 'source';
        this.diffBase = 'current';
        this.diffLines = [];
        this.diffStats = null;
        this.showHistory = true;
        await this.loadHistory();
      },

      switchHistoryTab: function (tab) {
        this.historyTab = tab;
        if (tab === 'diff') this.loadDiff();
      },

      loadDiff: async function () {
        if (!this.selectedVersion) {
          this.diffLines = [];
          this.diffStats = null;
          return;
        }
        var url = '/api/diff/' + encodePath(this.historyPath)
          + '?from=' + encodeURIComponent(this.diffBase)
          + '&to=' + encodeURIComponent(this.selectedVersion);
        try {
          var data = await api('GET', url);
          this.diffLines = data.lines || [];
          this.diffStats = data.stats || null;
        } catch (error) {
          this.diffLines = [];
          this.diffStats = null;
          this.notify('差异计算失败：' + error.message, 'error');
        }
      },

      loadHistory: async function () {
        if (!this.historyPath) return;
        try {
          var data = await api('GET', '/api/history/' + encodePath(this.historyPath));
          this.historyVersions = data.versions || [];
          if (this.selectedVersion
              && !this.historyVersions.some(function (item) {
                return item.id === this.selectedVersion;
              }, this)) {
            this.selectedVersion = '';
            this.versionContent = '';
            this.versionSame = null;
          }
        } catch (error) {
          this.notify('历史版本加载失败：' + error.message, 'error');
        }
      },

      previewVersion: async function (versionId) {
        if (this.historyBusy) return;
        this.historyBusy = true;
        try {
          var data = await api('GET', '/api/versions/' + encodeURIComponent(versionId));
          this.selectedVersion = versionId;
          this.versionContent = data.content || '';
          this.versionSame = this.versionContent === this.content;
          if (this.historyTab === 'diff') await this.loadDiff();
        } catch (error) {
          this.notify('读取版本失败：' + error.message, 'error');
        } finally {
          this.historyBusy = false;
        }
      },

      restoreVersion: async function () {
        if (!this.selectedVersion || this.historyBusy) return;
        if (!window.confirm('把文档还原到所选版本？当前内容会保留为一个新的历史版本。')) return;
        this.historyBusy = true;
        try {
          var result = await api('POST', '/api/history/restore',
            { path: this.historyPath, version_id: this.selectedVersion });
          var data = await api('GET', '/api/docs/' + encodePath(this.historyPath));
          this.currentPath = data.path;
          this.content = data.content;
          this.original = data.content;
          await this.loadHistory();
          await this.refreshTree();
          this.versionSame = this.versionContent === this.content;
          if (this.historyTab === 'diff') await this.loadDiff();
          this.notify('已还原到 v' + result.version_number + '（生成新版本）', 'success');
        } catch (error) {
          this.notify('还原版本失败：' + error.message, 'error');
        } finally {
          this.historyBusy = false;
        }
      },

      clearHistory: async function () {
        if (this.historyBusy) return;
        if (!window.confirm('清空这篇文档的全部历史版本？不可恢复。')) return;
        this.historyBusy = true;
        try {
          await api('DELETE', '/api/history/' + encodePath(this.historyPath));
          this.selectedVersion = '';
          this.versionContent = '';
          this.versionSame = null;
          this.diffLines = [];
          this.diffStats = null;
          await this.loadHistory();
          this.notify('历史版本已清空', 'success');
        } catch (error) {
          this.notify('清空历史失败：' + error.message, 'error');
        } finally {
          this.historyBusy = false;
        }
      },

      syncHash: function () {
        if (this.currentPath) setHash('doc', this.currentPath);
        else if (this.activeDirPath) setHash('dir', this.activeDirPath);
        else setHash('dir', '');
      },

      openFromHash: function () {
        var hash = window.location.hash || '';
        if (hash.indexOf('#/dir/') === 0) {
          var dir;
          try { dir = decodeURIComponent(hash.slice(6)); } catch (error) { return; }
          if (dir) this.openDir(dir);
          return;
        }
        if (hash.indexOf('#/doc/') !== 0) return;
        var path;
        try { path = decodeURIComponent(hash.slice(6)); } catch (error) { return; }
        if (!path) return;
        var index = path.lastIndexOf('/');
        if (index > 0) this.activeDirPath = path.slice(0, index);
        if (path !== this.currentPath) this.selectDoc(path);
      },

      openDir: function (path) {
        if (!path || !this.confirmDiscard()) return;
        this.activeDirPath = path;
        this.selectedDir = path;
        this.currentPath = '';
        this.content = '';
        this.original = '';
        this.editing = false;
        setHash('dir', path);
      },

      goToCards: function () {
        if (!this.confirmDiscard()) return;
        this.activeDirPath = '';
        this.selectedDir = '';
        this.currentPath = '';
        this.content = '';
        this.original = '';
        this.editing = false;
        setHash('dir', '');
      },

      goBack: function () {
        if (!this.confirmDiscard()) return;
        if (this.currentPath) {
          this.currentPath = '';
          this.content = '';
          this.original = '';
          this.editing = false;
          this.syncHash();
          return;
        }
        if (this.activeDirPath) {
          var parts = this.activeDirPath.split('/');
          if (parts.length > 1) this.openDir(parts.slice(0, -1).join('/'));
          else this.goToCards();
        }
      },

      selectDir: function (path) {
        this.selectedDir = this.selectedDir === path ? '' : path;
      },

      clearSelectedDir: function () { this.selectedDir = ''; },

      openContextMenu: function (event, node) {
        if (!node || !node.path) return;
        this.contextMenu = {
          x: Math.max(8, Math.min(event.clientX, window.innerWidth - 190)),
          y: Math.max(8, Math.min(event.clientY, window.innerHeight - 220)),
          node: node
        };
      },

      closeContextMenu: function () { this.contextMenu = null; },

      openFromMenu: function () {
        if (!this.contextMenu) return;
        var node = this.contextMenu.node;
        this.closeContextMenu();
        if (node.type === 'dir') this.openDir(node.path);
        else this.selectDoc(node.path);
      },

      startNewInMenu: function (kind) {
        if (!this.contextMenu) return;
        var node = this.contextMenu.node;
        this.closeContextMenu();
        this.createIn(node.path, kind);
      },

      createIn: function (dirPath, kind) {
        if (!dirPath || !this.confirmDiscard()) return;
        this.selectedDir = dirPath;
        this.newKind = kind || 'dir';
        this.newName = '';
        this.showNew = true;
        var self = this;
        Vue.nextTick(function () {
          if (self.$refs.newNameInput) self.$refs.newNameInput.focus();
        });
      },

      openMoveDialog: function () {
        if (!this.contextMenu) return;
        var node = this.contextMenu.node;
        this.moveSource = { path: node.path, name: node.name, type: node.type };
        var index = node.path.lastIndexOf('/');
        var parent = index > 0 ? node.path.slice(0, index) : '';
        this.moveTarget = node.type === 'file' ? parent : '';
        this.closeContextMenu();
        var options = this.moveOptions;
        var target = this.moveTarget;
        // 默认目标不在候选列表中时，选中第一项。
        if (!options.some(function (item) { return item.path === target; })) {
          this.moveTarget = options.length ? options[0].path : '';
        }
        this.showMove = true;
      },

      submitMove: function () {
        if (!this.moveOptions.length) return;
        var source = this.moveSource.path;
        var target = this.moveTarget;
        this.showMove = false;
        this.moveEntry(source, target);
      },

      moveEntry: async function (sourcePath, targetDir) {
        if (!sourcePath) return;
        var prefix = sourcePath + '/';
        if (targetDir === sourcePath || targetDir.indexOf(prefix) === 0) {
          this.notify('不能把目录移动到它自己或它的子目录中', 'error');
          return;
        }
        if (/\.md$/i.test(sourcePath) && !targetDir) {
          this.notify('文档必须移动到某个目录中，不能直接放在文档库顶层', 'error');
          return;
        }
        try {
          var result = await api('PATCH', '/api/move',
            { path: sourcePath, target_dir: targetDir });
          if (result.moved) this.rewritePaths(sourcePath, result.path);
          await this.refreshTree();
          this.notify(result.moved
            ? '已移动到 ' + (targetDir || '文档库顶层')
            : '条目已在该目录中', 'success');
        } catch (error) {
          this.notify('移动失败：' + error.message, 'error');
        }
      },

      onDragStart: function (event, node) {
        if (!node || !node.path) return;
        this.draggingPath = node.path;
        try {
          event.dataTransfer.effectAllowed = 'move';
          event.dataTransfer.setData('text/plain', node.path);
        } catch (error) { /* 某些浏览器限制 dataTransfer，使用内存状态兜底 */ }
      },

      onDragEnd: function () {
        this.draggingPath = '';
        this.dropTarget = '';
      },

      onDragOver: function (event, targetPath) {
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
        this.dropTarget = targetPath;
      },

      onDragLeave: function (targetPath) {
        if (this.dropTarget === targetPath) this.dropTarget = '';
      },

      onDrop: function (event, targetPath) {
        var source = '';
        try { source = event.dataTransfer.getData('text/plain') || ''; } catch (error) { /* 忽略 */ }
        if (!source) source = this.draggingPath;
        this.draggingPath = '';
        this.dropTarget = '';
        if (source) this.moveEntry(source, targetPath);
      },

      deleteFromMenu: async function (recursive) {
        if (!this.contextMenu) return;
        var node = this.contextMenu.node;
        this.closeContextMenu();
        var label = node.type === 'dir' ? '目录' : '文档';
        var url = node.type === 'dir'
          ? '/api/dirs/' + encodePath(node.path)
          : '/api/docs/' + encodePath(node.path);
        if (recursive) {
          var typed = window.prompt(
            '将把目录「' + node.name + '」及其全部子目录与文档移入回收站（可还原）。\n请输入目录名以确认：', '');
          if (typed === null) return;
          if (typed.trim() !== node.name) {
            this.notify('名称不匹配，已取消删除', 'error');
            return;
          }
          url += '?recursive=true&confirm=' + encodeURIComponent(node.name);
        } else {
          var warning = node.type === 'dir'
            ? '仅空目录可删除；非空目录请使用右键「清空并移入回收站…」。删除后可在顶栏回收站还原。'
            : '删除后可在顶栏回收站还原。';
          if (!window.confirm('确定删除' + label + '「' + node.name + '」吗？' + warning)) return;
        }
        try {
          var result = await api('DELETE', url);
          if (node.type === 'file' && this.currentPath === node.path) {
            this.currentPath = '';
            this.content = '';
            this.original = '';
            this.editing = false;
          }
          if (node.type === 'dir' && this.currentPath
              && (this.currentPath === node.path
                  || this.currentPath.indexOf(node.path + '/') === 0)) {
            this.currentPath = '';
            this.content = '';
            this.original = '';
            this.editing = false;
          }
          if (node.type === 'dir' && this.activeDirPath
              && (this.activeDirPath === node.path
                  || this.activeDirPath.indexOf(node.path + '/') === 0)) {
            var parts = node.path.split('/');
            if (parts.length > 1) this.openDir(parts.slice(0, -1).join('/'));
            else this.goToCards();
          }
          if (this.selectedDir === node.path
              || this.selectedDir.indexOf(node.path + '/') === 0) {
            this.selectedDir = '';
          }
          this.syncHash();
          await this.refreshTree();
          await this.refreshTrashCount();
          this.notify(label + (result.recursive ? '及全部内容' : '')
            + '已移入回收站，可在顶栏还原（编号 ' + result.trash_id + '）', 'success');
        } catch (error) {
          this.notify('删除失败：' + error.message, 'error');
        }
      },

      startRename: function () {
        if (!this.contextMenu) return;
        var node = this.contextMenu.node;
        this.renameTarget = { path: node.path, name: node.name, type: node.type };
        this.renameName = node.name;
        this.closeContextMenu();
        this.showRename = true;
        var self = this;
        Vue.nextTick(function () {
          if (self.$refs.renameInput) {
            self.$refs.renameInput.focus();
            self.$refs.renameInput.select();
          }
        });
      },

      startDescriptionFromMenu: function () {
        if (!this.contextMenu) return;
        var node = this.contextMenu.node;
        this.closeContextMenu();
        this.openDescription({ path: node.path, description: node.description || '' });
      },

      rewritePaths: function (oldPath, newPath) {
        var prefix = oldPath + '/';
        if (this.currentPath === oldPath) {
          this.currentPath = newPath;
        } else if (this.currentPath.indexOf(prefix) === 0) {
          this.currentPath = newPath + this.currentPath.slice(oldPath.length);
        }
        if (this.activeDirPath === oldPath) {
          this.activeDirPath = newPath;
        } else if (this.activeDirPath.indexOf(prefix) === 0) {
          this.activeDirPath = newPath + this.activeDirPath.slice(oldPath.length);
        }
        if (this.selectedDir === oldPath) {
          this.selectedDir = newPath;
        } else if (this.selectedDir.indexOf(prefix) === 0) {
          this.selectedDir = newPath + this.selectedDir.slice(oldPath.length);
        }
        this.syncHash();
      },

      submitRename: async function () {
        var name = this.renameName.trim();
        if (!name) { this.notify('请输入新名称', 'error'); return; }
        if (name.indexOf('/') !== -1 || name.indexOf('\\') !== -1
            || name.indexOf('..') !== -1 || name.charAt(0) === '.') {
          this.notify('名称不能包含路径分隔符、.. 或以点开头', 'error');
          return;
        }
        if (this.renameTarget.type === 'file' && !/\.md$/i.test(name)) name += '.md';
        var oldPath = this.renameTarget.path;
        try {
          var result = await api('PATCH', '/api/rename', { path: oldPath, new_name: name });
          this.showRename = false;
          this.rewritePaths(oldPath, result.path);
          await this.refreshTree();
          this.notify(result.renamed ? '重命名成功' : '名称未变化', 'success');
        } catch (error) {
          this.notify('重命名失败：' + error.message, 'error');
        }
      },

      openDescription: function (card) {
        this.descriptionTarget = card.path;
        this.descriptionText = card.description || '';
        this.showDescription = true;
      },

      submitDescription: async function () {
        try {
          await api('PUT', '/api/descriptions/' + encodePath(this.descriptionTarget),
            { content: this.descriptionText });
          this.showDescription = false;
          await this.refreshTree();
          this.notify('目录说明已保存', 'success');
        } catch (error) {
          this.notify('保存说明失败：' + error.message, 'error');
        }
      },

      confirmDiscard: function () {
        if (!this.dirty) return true;
        return window.confirm('当前文档有未保存的修改，确定放弃吗？');
      },

      toggleToc: function () {
        this.showToc = !this.showToc;
        saveTocVisible(this.showToc);
        if (this.showToc) this.refreshActiveHeading();
      },

      // 窄屏浮层的临时关闭：不写入偏好，下次仍按用户设置展示。
      closeToc: function () {
        if (window.innerWidth <= 900) this.showToc = false;
      },

      isCollapsed: function (headingId) {
        return !!this.collapsedHeadings[headingId];
      },

      // 折叠 / 展开单个标题下的子目录；整体替换对象以触发视图更新。
      toggleHeading: function (headingId) {
        var next = Object.assign({}, this.collapsedHeadings);
        if (next[headingId]) delete next[headingId];
        else next[headingId] = true;
        this.collapsedHeadings = next;
        // 高亮项可能刚好被折叠隐藏，重算到最近可见的祖先标题。
        this.refreshActiveHeading();
      },

      collapseAll: function () {
        var next = {};
        this.docOutline.forEach(function (item) {
          if (item.hasChildren) next[item.id] = true;
        });
        this.collapsedHeadings = next;
        this.refreshActiveHeading();
      },

      expandAll: function () {
        this.collapsedHeadings = {};
      },

      scrollToHeading: function (headingId) {
        var container = this.$refs.viewerScroll;
        if (!container) return;
        var node = container.querySelector('[id="' + headingId + '"]');
        if (!node) return;
        var offset = node.getBoundingClientRect().top
          - container.getBoundingClientRect().top + container.scrollTop - 12;
        try {
          container.scrollTo({ top: Math.max(0, offset), behavior: 'smooth' });
        } catch (error) {
          container.scrollTop = Math.max(0, offset);
        }
        this.activeHeading = headingId;
        // 窄屏下目录是浮层，点完就收起，避免遮住正文。
        if (window.innerWidth <= 900) this.showToc = false;
      },

      refreshActiveHeading: function () {
        var container = this.$refs.viewerScroll;
        if (!container) return;
        this.highlightHeadingAt(container);
      },

      highlightHeadingAt: function (container) {
        if (!this.docOutline.length) {
          if (this.activeHeading) this.activeHeading = '';
          return;
        }
        var threshold = container.getBoundingClientRect().top + 90;
        var current = '';
        for (var i = 0; i < this.docOutline.length; i += 1) {
          var node = container.querySelector('[id="' + this.docOutline[i].id + '"]');
          if (!node) continue;
          if (node.getBoundingClientRect().top <= threshold) current = this.docOutline[i].id;
          else break;
        }
        current = this.resolveVisibleHeading(current);
        if (this.activeHeading !== current) this.activeHeading = current;
      },

      // 当前标题被父级折叠隐藏时，向上找到最近一个可见的祖先标题来高亮。
      resolveVisibleHeading: function (headingId) {
        var visible = this.visibleHeadingIds;
        var map = this.headingById;
        var current = headingId;
        while (current) {
          if (visible[current]) return current;
          current = map[current] ? map[current].parentId : '';
        }
        return '';
      },

      // 滚动正文时同步目录高亮，用 rAF 节流避免高频 layout 查询。
      onViewerScroll: function (event) {
        var container = event.target;
        if (!container || this.tocScrollTick) return;
        var self = this;
        this.tocScrollTick = true;
        window.requestAnimationFrame(function () {
          self.tocScrollTick = false;
          self.highlightHeadingAt(container);
        });
      },

      selectDoc: async function (path) {
        if (path === this.currentPath) return;
        if (!this.confirmDiscard()) return;
        try {
          var data = await api('GET', '/api/docs/' + encodePath(path));
          this.currentPath = data.path;
          this.content = data.content;
          this.original = data.content;
          this.editing = false;
          this.activeHeading = '';
          this.collapsedHeadings = {};
          var self = this;
          Vue.nextTick(function () {
            var container = self.$refs.viewerScroll;
            if (container) container.scrollTop = 0;
            var tocList = self.$refs.tocList;
            if (tocList) tocList.scrollTop = 0;
          });
          setHash('doc', data.path);
        } catch (error) {
          this.notify('读取失败：' + error.message, 'error');
        }
      },

      toggleEdit: function () { if (this.currentPath) this.editing = !this.editing; },

      saveDoc: async function () {
        if (!this.currentPath || this.saving) return;
        this.saving = true;
        try {
          var result = await api('PUT', '/api/docs/' + encodePath(this.currentPath), { content: this.content });
          this.original = this.content;
          if (this.showHistory && this.historyPath === this.currentPath) {
            await this.loadHistory();
          }
          this.notify(result.version
            ? (result.action === 'created' ? '已创建并保存' : '已覆盖更新并保存')
              + '（v' + result.version_number + '）'
            : '内容未变化，未新增历史版本', 'success');
          await this.refreshTree();
        } catch (error) {
          this.notify('保存失败：' + error.message, 'error');
        } finally {
          this.saving = false;
        }
      },

      deleteDoc: async function () {
        if (!this.currentPath) return;
        if (!window.confirm('确定删除「' + this.currentPath
            + '」吗？删除后会移入回收站，可在顶栏还原。')) return;
        try {
          await api('DELETE', '/api/docs/' + encodePath(this.currentPath));
          this.currentPath = '';
          this.content = '';
          this.original = '';
          this.editing = false;
          this.syncHash();
          await this.refreshTree();
          await this.refreshTrashCount();
          this.notify('文档已移入回收站，可在顶栏还原', 'success');
        } catch (error) {
          this.notify('删除失败：' + error.message, 'error');
        }
      },

      openNewDialog: function () {
        if (!this.confirmDiscard()) return;
        this.newKind = this.selectedDir ? 'doc' : 'dir';
        this.newName = '';
        this.showNew = true;
        var self = this;
        Vue.nextTick(function () {
          if (self.$refs.newNameInput) self.$refs.newNameInput.focus();
        });
      },

      createEntry: async function () {
        var name = this.newName.trim();
        if (!name) { this.notify('请输入名称', 'error'); return; }
        if (name.indexOf('..') !== -1 || name.indexOf('/') !== -1 || name.indexOf('\\') !== -1
            || name === '.' || name.charAt(0) === '.') {
          this.notify('名称不能包含路径分隔符、.. 或以点开头', 'error');
          return;
        }
        var base = this.selectedDir;
        if (this.newKind === 'doc' && !base) {
          this.notify('请先选中一个目录再新建文档', 'error');
          return;
        }

        if (this.newKind === 'dir') {
          var dirPath = base ? base + '/' + name : name;
          try {
            var dirResult = await api('POST', '/api/dirs/' + encodePath(dirPath));
            this.showNew = false;
            this.selectedDir = dirResult.path;
            await this.refreshTree();
            this.notify(dirResult.created ? '目录已创建并选中' : '目录已存在，已选中', 'success');
          } catch (error) {
            this.notify('创建目录失败：' + error.message, 'error');
          }
          return;
        }

        var fileName = /\.md$/i.test(name) ? name : name + '.md';
        var docPath = base + '/' + fileName;
        var initial = '# ' + fileName.replace(/\.md$/i, '') + '\n\n';
        try {
          var docResult = await api('PUT', '/api/docs/' + encodePath(docPath), { content: initial });
          this.showNew = false;
          this.currentPath = docResult.path;
          this.content = initial;
          this.original = initial;
          this.editing = true;
          setHash('doc', docResult.path);
          await this.refreshTree();
          this.notify('文档已创建，可直接编辑', 'success');
        } catch (error) {
          this.notify('创建文档失败：' + error.message, 'error');
        }
      }
    }
  });

  app.mount('#app');
})();

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
        noticeTimer: null,
        keyHandler: null,
        hashHandler: null,
        docClickHandler: null
      };
    },

    computed: {
      renderedHtml: function () { return renderMarkdown(this.content); },
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
      renderedHtml: function () { Vue.nextTick(decorate); },
      editing: function () { Vue.nextTick(decorate); },
      currentPath: function () {
        if (this.showHistory && this.currentPath !== this.historyPath) {
          this.showHistory = false;
        }
      },
      content: function () {
        if (this.selectedVersion && this.versionContent !== '') {
          this.versionSame = this.versionContent === this.content;
        }
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
        this.showHistory = true;
        await this.loadHistory();
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

      selectDoc: async function (path) {
        if (path === this.currentPath) return;
        if (!this.confirmDiscard()) return;
        try {
          var data = await api('GET', '/api/docs/' + encodePath(path));
          this.currentPath = data.path;
          this.content = data.content;
          this.original = data.content;
          this.editing = false;
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

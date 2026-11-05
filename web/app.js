/* MDFileManager 前端：文档树 + 目录选中 + 分类新建 + Markdown 渲染（含公式）+ 编辑保存。
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

  var TreeNode = {
    name: 'TreeNode',
    props: {
      node: { type: Object, required: true },
      current: { type: String, default: '' },
      selectedDir: { type: String, default: '' },
      expanded: { type: Object, required: true },
      depth: { type: Number, default: 0 }
    },
    emits: ['select', 'select-dir', 'toggle'],
    template: '#tree-node-tpl',
    methods: {
      onClick: function () {
        if (this.node.type === 'dir') this.$emit('select-dir', this.node.path);
        else this.$emit('select', this.node.path);
      }
    }
  };

  var app = Vue.createApp({
    data: function () {
      return {
        tree: [],
        expanded: {},
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
        noticeTimer: null,
        keyHandler: null,
        hashHandler: null
      };
    },

    computed: {
      renderedHtml: function () { return renderMarkdown(this.content); },
      dirty: function () { return this.content !== this.original; },
      docCount: function () {
        function count(nodes) {
          return nodes.reduce(function (total, node) {
            return total + (node.type === 'file' ? 1 : count(node.children || []));
          }, 0);
        }
        return count(this.tree);
      },
      newLocation: function () {
        return this.selectedDir ? this.selectedDir + '/' : 'data/（顶层）';
      },
      newPlaceholder: function () {
        return this.newKind === 'dir' ? '例如 前端笔记' : '例如 渲染说明.md';
      },
      newHint: function () {
        if (!this.selectedDir) {
          return '未选中目录时只能创建顶层目录。点击左侧目录名可选中它，之后即可创建子目录或 .md 文档。';
        }
        return this.newKind === 'dir'
          ? '将在选中目录下创建子目录，创建后会自动选中新目录。'
          : '文件名可省略 .md（自动补全）；同名保存为覆盖更新。';
      }
    },

    watch: {
      renderedHtml: function () { Vue.nextTick(decorate); },
      editing: function () { Vue.nextTick(decorate); }
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
      window.addEventListener('keydown', this.keyHandler);
      window.addEventListener('hashchange', this.hashHandler);
      this.checkHealth();
      this.refreshTree().then(function () { self.openFromHash(); });
    },

    beforeUnmount: function () {
      window.removeEventListener('keydown', this.keyHandler);
      window.removeEventListener('hashchange', this.hashHandler);
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
          var expanded = this.expanded;
          function expandAll(nodes) {
            nodes.forEach(function (node) {
              if (node.type === 'dir') {
                if (expanded[node.path] === undefined) expanded[node.path] = true;
                expandAll(node.children || []);
              }
            });
          }
          expandAll(this.tree);
        } catch (error) {
          this.notify('目录树加载失败：' + error.message, 'error');
        }
      },

      openFromHash: function () {
        var hash = window.location.hash || '';
        if (hash.indexOf('#/dir/') === 0) {
          var dir;
          try { dir = decodeURIComponent(hash.slice(6)); } catch (error) { return; }
          if (dir) {
            this.selectedDir = dir;
            this.expanded[dir] = true;
          }
          return;
        }
        if (hash.indexOf('#/doc/') !== 0) return;
        var path;
        try { path = decodeURIComponent(hash.slice(6)); } catch (error) { return; }
        if (path && path !== this.currentPath) this.selectDoc(path);
      },

      selectDir: function (path) {
        this.selectedDir = this.selectedDir === path ? '' : path;
        if (this.selectedDir) this.expanded[path] = true;
        setHash('dir', this.selectedDir);
      },

      clearSelectedDir: function () {
        this.selectedDir = '';
        setHash('dir', '');
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

      toggleNode: function (path) { this.expanded[path] = !this.expanded[path]; },
      toggleEdit: function () { if (this.currentPath) this.editing = !this.editing; },

      saveDoc: async function () {
        if (!this.currentPath || this.saving) return;
        this.saving = true;
        try {
          var result = await api('PUT', '/api/docs/' + encodePath(this.currentPath), { content: this.content });
          this.original = this.content;
          this.notify(result.action === 'created' ? '已创建并保存' : '已覆盖更新并保存', 'success');
          await this.refreshTree();
        } catch (error) {
          this.notify('保存失败：' + error.message, 'error');
        } finally {
          this.saving = false;
        }
      },

      deleteDoc: async function () {
        if (!this.currentPath) return;
        if (!window.confirm('确定删除「' + this.currentPath + '」吗？此操作不可撤销。')) return;
        try {
          await api('DELETE', '/api/docs/' + encodePath(this.currentPath));
          this.currentPath = '';
          this.content = '';
          this.original = '';
          this.editing = false;
          setHash('doc', '');
          this.notify('文档已删除', 'success');
          await this.refreshTree();
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
        if (!name) {
          this.notify('请输入名称', 'error');
          return;
        }
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
            this.expanded[dirResult.path] = true;
            setHash('dir', dirResult.path);
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

  app.component('tree-node', TreeNode);
  app.mount('#app');
})();

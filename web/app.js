/* MDFileManager 阶段二前端：文档树 + Markdown 高保真渲染 + 编辑保存。
 * 纯静态 JS，通过 Fetch 调用阶段一的 JSON API，无任何构建步骤。 */
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

  function renderMarkdown(source) {
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

  function encodeDocPath(path) {
    return String(path).split('/').map(encodeURIComponent).join('/');
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
      expanded: { type: Object, required: true },
      depth: { type: Number, default: 0 }
    },
    emits: ['select', 'toggle'],
    template: '#tree-node-tpl',
    methods: {
      onClick: function () {
        if (this.node.type === 'dir') this.$emit('toggle', this.node.path);
        else this.$emit('select', this.node.path);
      }
    }
  };

  var app = Vue.createApp({
    data: function () {
      return {
        tree: [],
        expanded: {},
        currentPath: '',
        content: '',
        original: '',
        editing: false,
        saving: false,
        backendOk: false,
        notice: null,
        showNew: false,
        newPath: 'Projects/新文档.md',
        noticeTimer: null,
        keyHandler: null
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
      }
    },

    watch: {
      renderedHtml: function () { Vue.nextTick(highlightAll); },
      editing: function () { Vue.nextTick(highlightAll); }
    },

    mounted: function () {
      var self = this;
      this.keyHandler = function (event) {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
          event.preventDefault();
          self.saveDoc();
        }
      };
      window.addEventListener('keydown', this.keyHandler);
      this.checkHealth();
      this.refreshTree();
    },

    beforeUnmount: function () {
      window.removeEventListener('keydown', this.keyHandler);
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

      confirmDiscard: function () {
        if (!this.dirty) return true;
        return window.confirm('当前文档有未保存的修改，确定放弃吗？');
      },

      selectDoc: async function (path) {
        if (path === this.currentPath) return;
        if (!this.confirmDiscard()) return;
        try {
          var data = await api('GET', '/api/docs/' + encodeDocPath(path));
          this.currentPath = data.path;
          this.content = data.content;
          this.original = data.content;
          this.editing = false;
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
          var result = await api('PUT', '/api/docs/' + encodeDocPath(this.currentPath), { content: this.content });
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
          await api('DELETE', '/api/docs/' + encodeDocPath(this.currentPath));
          this.currentPath = '';
          this.content = '';
          this.original = '';
          this.editing = false;
          this.notify('文档已删除', 'success');
          await this.refreshTree();
        } catch (error) {
          this.notify('删除失败：' + error.message, 'error');
        }
      },

      openNewDialog: function () {
        if (!this.confirmDiscard()) return;
        this.newPath = 'Projects/新文档.md';
        this.showNew = true;
        var self = this;
        Vue.nextTick(function () {
          if (self.$refs.newPathInput) {
            self.$refs.newPathInput.focus();
            self.$refs.newPathInput.select();
          }
        });
      },

      createDoc: async function () {
        var path = this.newPath.trim();
        if (!/\.md$/i.test(path)) {
          this.notify('文件名必须以 .md 结尾', 'error');
          return;
        }
        if (path.indexOf('..') !== -1 || path.charAt(0) === '/' || path.charAt(0) === '\\') {
          this.notify('路径不能包含 .. 或以 / 开头', 'error');
          return;
        }
        var initial = '# ' + path.split('/').pop().replace(/\.md$/i, '') + '\n\n';
        try {
          var result = await api('PUT', '/api/docs/' + encodeDocPath(path), { content: initial });
          this.showNew = false;
          this.currentPath = result.path;
          this.content = initial;
          this.original = initial;
          this.editing = true;
          await this.refreshTree();
          this.notify('文档已创建，可直接编辑', 'success');
        } catch (error) {
          this.notify('创建失败：' + error.message, 'error');
        }
      }
    }
  });

  app.component('tree-node', TreeNode);
  app.mount('#app');
})();

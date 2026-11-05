/* MDFileManager 数学公式支持：为 marked 注册 $$...$$ / $...$ 扩展。
 * 公式先转成占位 span，等 DOMPurify 净化、Vue 挂载之后再由 KaTeX 原地渲染，
 * 这样既不会被 marked 的反斜杠转义破坏，也不会让 KaTeX 生成的样式被净化器改写。
 * 浏览器：window.MDFMMath；Node 校验：require('./math.js')。
 */
(function (global) {
  'use strict';

  function createMathRenderer(marked, katex) {
    var store = [];

    function placeholder(expr, display) {
      var index = store.push({ expr: expr, display: display }) - 1;
      return '<span class="math-placeholder" data-math-index="' + index + '"></span>';
    }

    var extensions = [
      {
        name: 'mathBlock',
        level: 'block',
        start: function (src) { return src.indexOf('$$'); },
        tokenizer: function (src) {
          var match = /^\$\$([\s\S]+?)\$\$(?:\n|$)/.exec(src);
          if (!match) return;
          return { type: 'mathBlock', raw: match[0], text: match[1].trim() };
        },
        renderer: function (token) { return placeholder(token.text, true) + '\n'; }
      },
      {
        name: 'mathInline',
        level: 'inline',
        start: function (src) { return src.indexOf('$'); },
        tokenizer: function (src) {
          var match = /^\$([^$\n]+?)\$/.exec(src);
          if (!match) return;
          return { type: 'mathInline', raw: match[0], text: match[1] };
        },
        renderer: function (token) { return placeholder(token.text, false); }
      }
    ];

    if (marked && typeof marked.use === 'function') {
      marked.use({ extensions: extensions });
    }

    return {
      reset: function () { store = []; },

      renderInto: function (root) {
        if (!katex || !root || typeof root.querySelectorAll !== 'function') return 0;
        var count = 0;
        root.querySelectorAll('.math-placeholder').forEach(function (node) {
          var item = store[Number(node.getAttribute('data-math-index'))];
          if (!item) return;
          try {
            katex.render(item.expr, node, {
              displayMode: item.display,
              throwOnError: false,
              output: 'html'
            });
            node.classList.remove('math-placeholder');
            count += 1;
          } catch (error) {
            node.textContent = item.display ? '$$' + item.expr + '$$' : '$' + item.expr + '$';
          }
        });
        return count;
      }
    };
  }

  var api = { install: createMathRenderer };
  if (typeof module === 'object' && module.exports) module.exports = api;
  global.MDFMMath = api;
})(typeof window !== 'undefined' ? window : globalThis);

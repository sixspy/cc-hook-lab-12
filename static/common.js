const 投递台 = {
  骨签: 'hook-12-停用端点联拒',

  async getJSON(url, opt) {
    const r = await fetch(url, opt);
    if (r.status === 401) { location.href = '/login'; throw new Error('未登录'); }
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      // 停用联拒错误带结构化中文拒因/归档号/入队成败，整包挂到异常上供页面直读。
      const err = new Error(data.拒因 || data.错误 || data.error || r.statusText);
      err.数据 = data || {};
      throw err;
    }
    return data;
  },
  async postJSON(url, body) {
    return this.getJSON(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
  },
  安全文本(s) {
    const d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  },
  徽章(状态, 额外类) {
    const span = document.createElement('span');
    span.className = '徽章 ' + (状态 || '') + (额外类 ? ' ' + 额外类 : '');
    span.textContent = 状态 || '—';
    return span;
  },
  行(html) {
    const tr = document.createElement('tr');
    tr.innerHTML = html;
    return tr;
  },
  空态(msg) { return msg || '暂无数据'; },

  // —— hook-12 共用：可点主链 / 中文命运 / 骨签条 ——
  事件链(事件号) {
    if (!事件号) return '<span class="命运">—</span>';
    return '<a class="链" href="/事件详情.html?事件号=' +
      encodeURIComponent(事件号) + '">' + this.安全文本(事件号) + '</a>';
  },
  端点链(端点键) {
    if (!端点键) return '—';
    return '<a class="链" href="/端点名册.html?端点键=' +
      encodeURIComponent(端点键) + '">' + this.安全文本(端点键) + '</a>';
  },
  // 事件状态 → 中文命运一句话
  命运文(状态) {
    return ({
      '待投': '命运：已入队，排队等待签名投递',
      '投递中': '命运：已出队，签名投递进行中',
      '已投递': '命运：对端已确认，投递完成',
      '死信': '命运：重试耗尽，已落入死信匣待处置',
    })[状态] || ('命运：' + (状态 || '未知'));
  },
  // 死信/处置状态
  匣命运(状态) {
    return ({
      '待处置': '命运：在死信匣中，等待重投或作废',
      '已重投': '命运：已重投，回到正式队列待投',
      '已作废': '命运：已人工作废，不再投递',
    })[状态] || ('命运：' + (状态 || '未知'));
  },
  骨签条(工程形态) {
    const div = document.createElement('div');
    div.className = '骨签条';
    div.innerHTML =
      '<span>骨签 <code>' + this.骨签 + '</code></span>' +
      '<span>规则：停用端点必须拒入队，名册启用灯与事件队列同票</span>' +
      (工程形态 ? '<span class="形">工程形态：' + this.安全文本(工程形态) + '</span>' : '');
    return div;
  },
  挂骨签(selector, 工程形态) {
    const host = typeof selector === 'string' ? document.querySelector(selector) : selector;
    if (host) host.prepend(this.骨签条(工程形态));
  },
  // 在指定元素里渲染一次入队/操作结果（成败灯 + 中文拒因）
  渲染成败(box, ok, 文本, 额外) {
    if (!box) return;
    box.innerHTML = '';
    const d = document.createElement('div');
    d.className = ok ? '成框' : '拒因框';
    d.textContent = (ok ? '✅ 入队成败：成功（入队成败=true）\n'
                        : '⛔ 入队成败：被拒（入队成败=false）\n') + 文本;
    box.appendChild(d);
    if (额外) {
      const g = document.createElement('div');
      g.className = '结果格';
      g.innerHTML = 额外;
      box.appendChild(g);
    }
  },
};

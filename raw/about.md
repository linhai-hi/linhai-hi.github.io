{% assign id = site.data.identity %}
{% if id and id.name and id.name != "" %}
<h2>{{ id.name }}</h2>
<p><strong>{{ id.role }}</strong></p>
<p>{{ id.summary }}</p>
{% if id.location and id.location.city and id.location.city != "" %}
<p>坐标：{{ id.location.city }}</p>
{% endif %}
{% if id.contact and id.contact.email and id.contact.email != "" %}
<p>联络（仅工作）：<a href="mailto:{{ id.contact.email }}">{{ id.contact.email }}</a></p>
{% endif %}
{% if id.contact and id.contact.github and id.contact.github != "" %}
<p>GitHub：<a href="{{ id.contact.github }}">{{ id.contact.github }}</a></p>
{% endif %}
<p class="muted">本页由 vault/profile.md 经闸门投影生成（site/_data/identity.json）。身份信息变更请改 vault 后重新投影，不直接改本页。</p>
{% else %}
<h2>关于（占位）</h2>
<p>本页内容来自 <code>vault/profile.md</code> 的公开投影。当前投影尚未生成。</p>
<p>生成方式：填写 vault 后运行 <code>python site/tools/gate.py project</code>，产出 <code>site/_data/identity.json</code>，本页自动填充。</p>
<p class="muted">投影只映射白名单字段且先过敏感信息闸门（docs/01 §5.2）；vault 其余文件一律不外传。</p>
{% endif %}

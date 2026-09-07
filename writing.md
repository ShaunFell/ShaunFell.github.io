---
layout: default
title: Writing
description: Essays by Shaun Fell on warp drives, black holes and the problem with gravity.
permalink: /writing/
---
<div class="page container">
  <header class="page__header">
    <h1 class="page__title">Writing</h1>
    <p class="page__subtitle">Longer pieces for a general audience. No equations required.</p>
  </header>
  <ul class="card-grid card-grid--3">
    {% for e in site.writing %}
    <li class="card">
      <a class="card__link" href="{{ e.url | relative_url }}">
        {% if e.image %}<img class="card__image" src="{{ e.image | relative_url }}" alt="" loading="lazy">{% endif %}
        <span class="card__body"><span class="card__title">{{ e.title }}</span><span class="card__text">{{ e.subtitle }}</span></span>
      </a>
    </li>
    {% endfor %}
  </ul>
</div>

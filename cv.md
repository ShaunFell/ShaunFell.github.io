---
layout: default
title: Curriculum Vitae
description: CV of Shaun D. B. Fell, theoretical physicist.
permalink: /cv/
---
{% assign p = site.data.profile %}
{% assign pubs = site.data.publications | where_exp: "x", "x.hidden != true" | sort: "date" | reverse %}
<div class="page container container--narrow">
  <header class="page__header">
    <h1 class="page__title">Curriculum Vitae</h1>
    <p class="page__subtitle">{{ p.name }} &middot; {{ p.position }}, {{ p.affiliation }}</p>
    {% if p.cv_pdf and p.cv_pdf != "" %}<p><a class="button button--ghost" href="{{ p.cv_pdf | relative_url }}"><svg class="icon"><use href="#i-doc"/></svg> Download PDF</a></p>{% endif %}
  </header>

  <section class="cv-section">
    <h2>Experience</h2>
    <ul class="cv-list">
      {% for e in site.data.experience %}
      <li class="cv-item">
        <span class="cv-item__when">{{ e.start }}&ndash;{{ e.end }}</span>
        <span>
          <span class="cv-item__title">{{ e.role }}</span><br>
          <span class="cv-item__org">{% if e.org_url %}<a href="{{ e.org_url }}" rel="noopener" target="_blank">{{ e.org }}</a>{% else %}{{ e.org }}{% endif %}{% if e.location %}, {{ e.location }}{% endif %}</span>
          {% if e.summary %}<span class="cv-item__note">{{ e.summary }}</span>{% endif %}
        </span>
      </li>
      {% endfor %}
    </ul>
  </section>

  <section class="cv-section">
    <h2>Education</h2>
    <ul class="cv-list">
      {% for e in site.data.education %}
      <li class="cv-item">
        <span class="cv-item__when">{{ e.start }}&ndash;{{ e.end }}</span>
        <span>
          <span class="cv-item__title">{{ e.degree }}</span><br>
          <span class="cv-item__org">{{ e.org }}{% if e.location %}, {{ e.location }}{% endif %}</span>
          {% if e.thesis %}<span class="cv-item__note">Thesis: {% if e.thesis_url %}<a href="{{ e.thesis_url }}" rel="noopener" target="_blank">{{ e.thesis }}</a>{% else %}{{ e.thesis }}{% endif %}</span>{% endif %}
        </span>
      </li>
      {% endfor %}
    </ul>
  </section>

  <section class="cv-section">
    <h2>Publications</h2>
    <p class="cv-item__note">Full details, abstracts and links on the <a href="{{ '/publications/' | relative_url }}">publications page</a>.</p>
    <ol class="cv-list" reversed>
      {% for pub in pubs %}{% include publication.html pub=pub compact=true %}{% endfor %}
    </ol>
  </section>

  <section class="cv-section">
    <h2>Talks</h2>
    <ul class="cv-list">
      {% for t in site.data.talks %}
      <li class="cv-item">
        <span class="cv-item__when">{{ t.year }}</span>
        <span><span class="cv-item__title">{{ t.title }}</span><br><span class="cv-item__org">{{ t.venue }}</span></span>
      </li>
      {% endfor %}
    </ul>
  </section>

  <section class="cv-section">
    <h2>Teaching</h2>
    <ul class="cv-list">
      {% for t in site.data.teaching %}
      <li class="cv-item">
        <span class="cv-item__when">{{ t.term }}</span>
        <span><span class="cv-item__title">{{ t.course }}</span><br><span class="cv-item__org">{{ t.role }}, {{ t.org }}</span></span>
      </li>
      {% endfor %}
    </ul>
  </section>
</div>

---
layout: default
title: Publications
description: Papers, preprints and software by Shaun Fell, updated automatically from INSPIRE-HEP.
permalink: /publications/
---
{% assign pubs = site.data.publications | where_exp: "x", "x.hidden != true" | sort: "date" | reverse %}
{% assign total_cites = 0 %}{% for x in pubs %}{% assign total_cites = total_cites | plus: x.citations %}{% endfor %}
{% assign articles = pubs | where: "type", "article" %}
{% assign preprints = pubs | where: "type", "preprint" %}
{% assign software = pubs | where: "type", "software" %}

<div class="page container">
  <header class="page__header">
    <h1 class="page__title">Publications</h1>
    <p class="page__subtitle">This list is refreshed automatically from <a href="https://inspirehep.net/authors?q=a%20{{ site.publications.inspire_bai }}" rel="noopener" target="_blank">INSPIRE-HEP</a> and <a href="https://orcid.org/{{ site.publications.orcid }}" rel="noopener" target="_blank">ORCID</a>. Citation counts are from INSPIRE.</p>
  </header>

  <ul class="stats" aria-label="Summary">
    <li><strong>{{ pubs | size }}</strong><span>publications</span></li>
    <li><strong>{{ articles | size }}</strong><span>peer-reviewed</span></li>
    <li><strong>{{ total_cites }}</strong><span>citations</span></li>
  </ul>

  <div class="filters" role="group" aria-label="Filter publications">
    <button type="button" data-filter="all" aria-pressed="true">All</button>
    {% if articles.size > 0 %}<button type="button" data-filter="article" aria-pressed="false">Journal articles</button>{% endif %}
    {% if preprints.size > 0 %}<button type="button" data-filter="preprint" aria-pressed="false">Preprints</button>{% endif %}
    {% if software.size > 0 %}<button type="button" data-filter="software" aria-pressed="false">Software</button>{% endif %}
    {% assign theses = pubs | where: "type", "thesis" %}{% if theses.size > 0 %}<button type="button" data-filter="thesis" aria-pressed="false">Thesis</button>{% endif %}
  </div>

  {% assign years = pubs | map: "year" | uniq %}
  {% for y in years %}
  <h2 class="pub-year">{{ y }}</h2>
  <div class="pub-list">
    {% for pub in pubs %}{% if pub.year == y %}{% include publication.html pub=pub %}{% endif %}{% endfor %}
  </div>
  {% endfor %}
</div>

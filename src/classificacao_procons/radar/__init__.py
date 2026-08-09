"""Radar de editais de fomento e patrocínio (nacionais e internacionais).

Monitora as principais fontes de fomento à pesquisa nas áreas de Direito, Saúde,
Administração e Educação, detecta editais/chamadas recém-abertos que sejam
relevantes para as áreas de interesse e notifica os pesquisadores por e-mail
assim que as oportunidades surgem.

O núcleo é offline e determinístico (``parser``, ``analise``, ``feeds`` de
parsing, ``serialization``), permitindo ``ruff``/``pytest`` sem rede. A coleta
real (``feeds.fetch_source``) e o envio (``notifier``) são isolados nas bordas.
"""

"""Optional Django integration: admin-protected backup download / restore views.

Wire it into a project's URLConf::

    path("dbs/", include("dbs.contrib.urls")),

Then superusers can visit ``/dbs/backup/`` to download an encrypted backup and
``/dbs/restore/`` to upload one. The passphrase is entered in the form and never
persisted server-side.
"""

FROM docker.io/library/python:3.12-slim
COPY wheelhouse /wheelhouse
RUN pip install --no-cache-dir --no-index --find-links /wheelhouse django-dbs \
    && rm -rf /wheelhouse \
    && useradd --uid 10001 --create-home shop \
    && install -d -o 10001 -g 10001 /app/data /var/backups/dbs
WORKDIR /app
COPY --chown=10001:10001 manage.py /app/manage.py
COPY --chown=10001:10001 shop /app/shop
COPY --chown=10001:10001 notes /app/notes
USER 10001
ENV DJANGO_SETTINGS_MODULE=shop.settings PYTHONUNBUFFERED=1
CMD ["sh", "-c", "python manage.py migrate --noinput && exec sleep infinity"]

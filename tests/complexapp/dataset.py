import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from django.core import serializers
from django.db.models import Sum

from dbs.crypto.kdf import KDFParams

from . import corpus
from .models import (
    Branch,
    EditingAssignment,
    Employee,
    EmployeeProfile,
    Keyword,
    Publisher,
    Review,
    Series,
    Volume,
    Writer,
)

SCALE = int(os.environ.get("DBS_STRESS_SCALE", "1"))

COUNTS = {
    Publisher: 40 * SCALE,
    Branch: 200 * SCALE,
    Employee: 3000 * SCALE,
    EmployeeProfile: 3000 * SCALE,
    Writer: 400 * SCALE,
    Keyword: 300 * SCALE,
    Series: 200 * SCALE,
    Volume: 4000 * SCALE,
    EditingAssignment: 8000 * SCALE,
    Review: 12000 * SCALE,
}

MODELS = list(COUNTS)

KEYWORDS_PER_VOLUME = 5

BATCH = 500

EPOCH = datetime(2020, 1, 1, tzinfo=timezone.utc)
EPOCH_DATE = date(2020, 1, 1)

STRESS_KDF = KDFParams(time_cost=1, memory_cost=8 * 1024, parallelism=1)


def populate(rng):
    publishers = Publisher.objects.bulk_create(
        [
            Publisher(
                name_en=f"{corpus.english_name(rng)} Press {index}",
                name_ar=f"دار {corpus.arabic_word(rng)} {corpus.to_arabic_digits(index)}",
                established=EPOCH_DATE + timedelta(days=rng.randrange(8000)),
                metadata=corpus.bilingual_json(rng),
                active=rng.random() < 0.8,
            )
            for index in range(COUNTS[Publisher])
        ],
        batch_size=BATCH,
    )

    branches = Branch.objects.bulk_create(
        [
            Branch(
                publisher=rng.choice(publishers),
                code=f"BR-{index:05d}",
                city_en=rng.choice(corpus.ENGLISH_WORDS).title(),
                city_ar=corpus.arabic_word(rng),
            )
            for index in range(COUNTS[Branch])
        ],
        batch_size=BATCH,
    )

    employees = []
    for start in range(0, COUNTS[Employee], BATCH):
        batch = []
        for _ in range(start, min(start + BATCH, COUNTS[Employee])):
            manager = rng.choice(employees) if employees and rng.random() < 0.7 else None
            batch.append(
                Employee(
                    branch=rng.choice(branches),
                    manager=manager,
                    full_name_en=corpus.english_name(rng),
                    full_name_ar=corpus.arabic_name(rng),
                    salary=Decimal(rng.randrange(300000, 2500000)) / 100,
                    hired_at=EPOCH + timedelta(minutes=rng.randrange(3000000)),
                    bio=corpus.bilingual_paragraph(rng) if rng.random() < 0.8 else "",
                    badge=rng.randbytes(16),
                )
            )
        employees.extend(Employee.objects.bulk_create(batch))

    EmployeeProfile.objects.bulk_create(
        [
            EmployeeProfile(
                employee=employee,
                slug=f"emp-{employee.pk}",
                preferences=corpus.bilingual_json(rng, 1),
            )
            for employee in employees
        ],
        batch_size=BATCH,
    )

    writers = Writer.objects.bulk_create(
        [
            Writer(
                name_en=corpus.english_name(rng),
                name_ar=corpus.arabic_name(rng),
                penname=f"pen-{index:04d}",
            )
            for index in range(COUNTS[Writer])
        ],
        batch_size=BATCH,
    )

    keywords = Keyword.objects.bulk_create(
        [
            Keyword(
                word_en=f"{rng.choice(corpus.ENGLISH_WORDS)}-{index}",
                word_ar=f"{corpus.arabic_word(rng)}-{corpus.to_arabic_digits(index)}",
            )
            for index in range(COUNTS[Keyword])
        ],
        batch_size=BATCH,
    )

    series_list = Series.objects.bulk_create(
        [
            Series(
                publisher=rng.choice(publishers) if rng.random() < 0.9 else None,
                title_en=corpus.english_sentence(rng, 4),
                title_ar=corpus.arabic_sentence(rng, 4),
            )
            for _ in range(COUNTS[Series])
        ],
        batch_size=BATCH,
    )

    positions = {}
    volumes = []
    for index in range(COUNTS[Volume]):
        series = rng.choice(series_list)
        positions[series.pk] = positions.get(series.pk, 0) + 1
        volumes.append(
            Volume(
                series=series,
                writer=rng.choice(writers),
                isbn=f"978-{index:09d}",
                position=positions[series.pk],
                price=Decimal(rng.randrange(500, 50000)) / 100,
                published=EPOCH + timedelta(minutes=rng.randrange(3000000)),
                summary=corpus.bilingual_json(rng, 1),
            )
        )
    volumes = Volume.objects.bulk_create(volumes, batch_size=BATCH)

    Volume.keywords.through.objects.bulk_create(
        [
            Volume.keywords.through(volume_id=volume.pk, keyword_id=keyword.pk)
            for volume in volumes
            for keyword in rng.sample(keywords, KEYWORDS_PER_VOLUME)
        ],
        batch_size=BATCH,
    )

    seen = set()
    assignments = []
    while len(assignments) < COUNTS[EditingAssignment]:
        volume = rng.choice(volumes)
        writer = rng.choice(writers)
        role = rng.choice(corpus.ROLES)
        key = (volume.pk, writer.pk, role)
        if key in seen:
            continue
        seen.add(key)
        assignments.append(
            EditingAssignment(
                volume=volume,
                writer=writer,
                role=role,
                started=EPOCH_DATE + timedelta(days=rng.randrange(2000)),
            )
        )
    EditingAssignment.objects.bulk_create(assignments, batch_size=BATCH)

    Review.objects.bulk_create(
        [
            Review(
                volume=rng.choice(volumes),
                reviewer_name=corpus.arabic_name(rng) if rng.random() < 0.5 else corpus.english_name(rng),
                rating=rng.randrange(1, 6),
                comment=f"{corpus.bilingual_paragraph(rng, rng.randrange(2, 5))} {corpus.mixed_direction(rng)}",
                created=EPOCH + timedelta(minutes=rng.randrange(3000000)),
            )
            for _ in range(COUNTS[Review])
        ],
        batch_size=BATCH,
    )


def snapshot():
    digests = {}
    for model in MODELS:
        m2m_names = [
            field.name
            for field in model._meta.many_to_many
            if field.remote_field.through._meta.auto_created
        ]
        raw = serializers.serialize("json", model._default_manager.order_by("pk").iterator())
        records = json.loads(raw)
        for record in records:
            for name in m2m_names:
                record["fields"][name] = sorted(record["fields"][name])
        canonical = json.dumps(records, sort_keys=True, ensure_ascii=False)
        digests[model._meta.label] = (len(records), hashlib.sha256(canonical.encode("utf-8")).hexdigest())
    return digests


def sample_rows(rng, per_model=20):
    def pick(model):
        pks = list(model._default_manager.order_by("pk").values_list("pk", flat=True))
        return [model._default_manager.get(pk=pk) for pk in rng.sample(pks, min(per_model, len(pks)))]

    def manager_chain(employee):
        chain = []
        node = employee
        while node.manager_id is not None:
            node = node.manager
            chain.append(node.pk)
        return chain

    employees = [
        {
            "pk": employee.pk,
            "full_name_en": employee.full_name_en,
            "full_name_ar": employee.full_name_ar,
            "salary": employee.salary,
            "hired_at": employee.hired_at,
            "bio": employee.bio,
            "badge": bytes(employee.badge),
            "manager_chain": manager_chain(employee),
            "profile_slug": employee.profile.slug,
            "preferences": employee.profile.preferences,
        }
        for employee in pick(Employee)
    ]

    volumes = [
        {
            "pk": volume.pk,
            "isbn": volume.isbn,
            "position": volume.position,
            "price": volume.price,
            "published": volume.published,
            "summary": volume.summary,
            "series_title_ar": volume.series.title_ar,
            "publisher_name_ar": volume.series.publisher.name_ar if volume.series.publisher_id else None,
            "keyword_ids": sorted(volume.keywords.values_list("pk", flat=True)),
            "editor_roles": sorted(volume.assignments.values_list("writer_id", "role")),
        }
        for volume in pick(Volume)
    ]

    reviews = [
        {
            "pk": review.pk,
            "reviewer_name": review.reviewer_name,
            "rating": review.rating,
            "comment": review.comment,
            "created": review.created,
            "volume_isbn": review.volume.isbn,
        }
        for review in pick(Review)
    ]

    publishers = [
        {
            "pk": publisher.pk,
            "name_en": publisher.name_en,
            "name_ar": publisher.name_ar,
            "established": publisher.established,
            "metadata": publisher.metadata,
            "active": publisher.active,
        }
        for publisher in pick(Publisher)
    ]

    return {
        "employees": employees,
        "volumes": volumes,
        "reviews": reviews,
        "publishers": publishers,
    }


def verify_samples(samples):
    for expected in samples["employees"]:
        employee = Employee.objects.get(pk=expected["pk"])
        assert employee.full_name_en == expected["full_name_en"]
        assert employee.full_name_ar.encode("utf-8") == expected["full_name_ar"].encode("utf-8")
        assert employee.salary == expected["salary"]
        assert employee.hired_at == expected["hired_at"]
        assert employee.bio == expected["bio"]
        assert bytes(employee.badge) == expected["badge"]
        chain = []
        node = employee
        while node.manager_id is not None:
            node = node.manager
            chain.append(node.pk)
        assert chain == expected["manager_chain"]
        assert employee.profile.slug == expected["profile_slug"]
        assert employee.profile.preferences == expected["preferences"]

    for expected in samples["volumes"]:
        volume = Volume.objects.get(pk=expected["pk"])
        assert volume.isbn == expected["isbn"]
        assert volume.position == expected["position"]
        assert volume.price == expected["price"]
        assert volume.published == expected["published"]
        assert volume.summary == expected["summary"]
        assert volume.series.title_ar.encode("utf-8") == expected["series_title_ar"].encode("utf-8")
        publisher_name = volume.series.publisher.name_ar if volume.series.publisher_id else None
        assert publisher_name == expected["publisher_name_ar"]
        assert sorted(volume.keywords.values_list("pk", flat=True)) == expected["keyword_ids"]
        assert sorted(volume.assignments.values_list("writer_id", "role")) == expected["editor_roles"]

    for expected in samples["reviews"]:
        review = Review.objects.get(pk=expected["pk"])
        assert review.reviewer_name == expected["reviewer_name"]
        assert review.rating == expected["rating"]
        assert review.comment.encode("utf-8") == expected["comment"].encode("utf-8")
        assert review.created == expected["created"]
        assert review.volume.isbn == expected["volume_isbn"]

    for expected in samples["publishers"]:
        publisher = Publisher.objects.get(pk=expected["pk"])
        assert publisher.name_en == expected["name_en"]
        assert publisher.name_ar.encode("utf-8") == expected["name_ar"].encode("utf-8")
        assert publisher.established == expected["established"]
        assert publisher.metadata == expected["metadata"]
        assert publisher.active == expected["active"]


def aggregates():
    return {
        "salary_total": Employee.objects.aggregate(total=Sum("salary"))["total"],
        "price_total": Volume.objects.aggregate(total=Sum("price"))["total"],
        "keyword_links": Volume.keywords.through.objects.count(),
        "assignments": EditingAssignment.objects.count(),
        "reports": Employee.objects.filter(manager__isnull=False).count(),
    }


def wipe():
    for model in reversed(MODELS):
        model._default_manager.all().delete()

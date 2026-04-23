from job_generator.catalogue import STATIC_JOBS, Job, load_catalogue


def test_static_jobs_count():
    assert len(STATIC_JOBS) == 20


def test_static_jobs_ids_unique():
    ids = [j.id for j in STATIC_JOBS]
    assert len(ids) == len(set(ids))


def test_static_jobs_all_have_description():
    for job in STATIC_JOBS:
        assert job.description.strip() != ""


def test_load_catalogue_no_extras():
    cat = load_catalogue([])
    assert len(cat) == 20


def test_load_catalogue_sorted():
    cat = load_catalogue([])
    ids = [j.id for j in cat]
    assert ids == sorted(ids)


def test_load_catalogue_extra_ids_added():
    cat = load_catalogue(["JOB-Z-001", "JOB-Z-002"])
    ids = [j.id for j in cat]
    assert "JOB-Z-001" in ids
    assert "JOB-Z-002" in ids
    assert len(cat) == 22


def test_load_catalogue_extra_ids_sorted_with_static():
    cat = load_catalogue(["JOB-AAAA-001"])
    ids = [j.id for j in cat]
    assert ids == sorted(ids)


def test_load_catalogue_extra_ids_deduped():
    cat = load_catalogue(["JOB-Z-001", "JOB-Z-001"])
    ids = [j.id for j in cat]
    assert ids.count("JOB-Z-001") == 1


def test_load_catalogue_extra_id_duplicate_of_static_ignored():
    cat = load_catalogue(["JOB-PICK-001"])
    ids = [j.id for j in cat]
    assert ids.count("JOB-PICK-001") == 1
    assert len(cat) == 20


def test_load_catalogue_extra_ids_description():
    cat = load_catalogue(["JOB-EXTRA-001"])
    extra = next(j for j in cat if j.id == "JOB-EXTRA-001")
    assert extra.description == "(extra)"


def test_load_catalogue_whitespace_stripped():
    cat = load_catalogue(["  JOB-Z-001  "])
    ids = [j.id for j in cat]
    assert "JOB-Z-001" in ids


def test_load_catalogue_empty_strings_ignored():
    cat = load_catalogue(["", "  "])
    assert len(cat) == 20

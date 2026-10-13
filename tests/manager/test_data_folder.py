from __future__ import annotations

import subprocess

from dbs.manager import cli, paths


def test_on_windows_a_new_data_folder_is_limited_to_its_owner(tmp_path):
    ran = []

    def run(command, **options):
        ran.append(command)
        return subprocess.CompletedProcess(command, 0)

    done = paths.restrict_to_owner(
        tmp_path,
        platform="win32",
        environ={"USERNAME": "sara", "USERDOMAIN": "OFFICE"},
        run=run,
    )

    assert done is True
    assert ran == [
        [
            "icacls",
            str(tmp_path),
            "/inheritance:r",
            "/grant:r",
            "OFFICE\\sara:(OI)(CI)F",
        ]
    ]


def test_elsewhere_the_folder_mode_is_enough(tmp_path):
    def run(command, **options):
        raise AssertionError("icacls only runs on Windows")

    assert paths.restrict_to_owner(tmp_path, platform="linux", run=run) is True


def test_a_failed_icacls_is_reported(tmp_path):
    def run(command, **options):
        return subprocess.CompletedProcess(command, 5)

    assert not paths.restrict_to_owner(
        tmp_path, platform="win32", environ={"USERNAME": "sara"}, run=run
    )


def test_only_a_folder_created_now_is_restricted(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        paths, "restrict_to_owner", lambda path: calls.append(path) or True
    )
    existing = tmp_path / "existing"
    existing.mkdir()

    paths.ensure_data_dir(tmp_path / "new")
    paths.ensure_data_dir(existing)

    assert calls == [tmp_path / "new"]


def test_an_import_stopped_between_its_two_moves_is_finished(tmp_path, capsys):
    home = tmp_path / "home"
    stage = paths.staging_path(home, "20261013T120000Z")
    paths.ensure_data_dir(stage)
    paths.write_private(paths.import_marker_path(stage), "")

    found = cli.resolve(type("Args", (), {"data_dir": str(home)})())

    assert found == home and home.is_dir() and not stage.exists()
    assert "Finished an import that stopped half way" in capsys.readouterr().err


def test_an_unfinished_stage_is_never_moved_into_place(tmp_path):
    home = tmp_path / "home"
    paths.ensure_data_dir(paths.staging_path(home, "20261013T120000Z"))

    assert paths.finish_interrupted_import(home) is None
    assert not home.exists()


def test_a_present_data_folder_is_left_alone(tmp_path):
    home = paths.ensure_data_dir(tmp_path / "home")
    stage = paths.staging_path(home, "20261013T120000Z")
    paths.ensure_data_dir(stage)
    paths.write_private(paths.import_marker_path(stage), "")

    assert paths.finish_interrupted_import(home) is None
    assert stage.exists()

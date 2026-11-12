import pytest

from dbs.manager.menu import explorer, sources
from dbs.manager.menu.explorer import (
    PICK_ANY,
    PICK_FILE,
    PICK_FOLDER,
    PICK_TARGET,
    PathDialog,
)
from dbs.manager.menu.screens.listing import FilesScreen, FoldersScreen
from dbs.manager.menu.sources import ApplicationFiles, LocalDisk
from tests.manager.servers.support import PASSWORD

pytestmark = pytest.mark.django_db


def shown(path):
    return str(path)[-40:]


@pytest.fixture
def media(project):
    folder = project / "media"
    (folder / "thumbs").mkdir()
    (folder / "logo.png").write_bytes(b"logo")
    (folder / "banner.jpg").write_bytes(b"b" * 2048)
    return folder


@pytest.fixture
def files(menu, application, media, local_host):
    screen = FilesScreen(menu.app, "web-1", "web-1")
    menu.app.push(screen)
    menu.press()
    return screen


@pytest.fixture
def here(tmp_path, monkeypatch):
    folder = tmp_path / "desk"
    folder.mkdir()
    monkeypatch.chdir(folder)
    return folder


def test_an_applications_folder_lists_folders_first_with_sizes(menu, files, media):
    assert files.explorer.path == str(media) and shown(media) in menu.screen
    lines = [
        line
        for line in menu.screen.splitlines()
        if "thumbs/" in line or ".png" in line or ".jpg" in line
    ]
    assert [
        "thumbs/" in lines[0],
        "banner.jpg" in lines[1],
        "logo.png" in lines[2],
    ] == [True] * 3
    assert "2.0 KB" in menu.line_with("banner.jpg") and "4 B" in menu.line_with(
        "logo.png"
    )


def test_enter_opens_a_folder_and_backspace_goes_up_to_where_it_was(menu, files, media):
    menu.press("enter")
    assert files.explorer.path == str(media / "thumbs")
    assert (
        shown(media / "thumbs") in menu.screen
        and "This folder is empty." in menu.screen
    )

    menu.press("backspace")
    assert files.explorer.path == str(media)
    assert files.explorer.selected.name == "thumbs"


def test_at_the_top_folder_backspace_leaves_the_explorer(menu, files):
    menu.press("backspace")

    assert menu.app.top is not files


def test_a_file_is_downloaded_to_a_folder_chosen_on_this_computer(menu, files, here):
    menu.press("down", "down", "d", "s")

    assert (here / "logo.png").read_bytes() == b"logo"
    assert menu.saw("Where to save logo.png") and menu.saw(shown(here))
    assert "Done." in menu.screen


def test_a_download_never_writes_over_a_file(menu, files, here):
    (here / "logo.png").write_bytes(b"mine")

    menu.press("down", "down", "d", "s")

    assert (here / "logo.png").read_bytes() == b"mine"
    assert "already exists; nothing was overwritten" in menu.screen


def test_a_download_can_be_given_another_name(menu, files, here):
    menu.press("down", "down", "d", "n", "copy.png", "enter")

    assert (here / "copy.png").read_bytes() == b"logo"


def test_a_folder_cannot_be_downloaded(menu, files, here):
    menu.press("d")

    assert "Select a file to download." in menu.screen
    assert list(here.iterdir()) == []


def test_a_file_from_this_computer_is_uploaded_into_the_folder_shown(
    menu, files, media, here
):
    (here / "notes.txt").write_text("notes")

    menu.press("u", "enter")
    assert (media / "notes.txt").read_text() == "notes"

    menu.press("enter")
    assert "notes.txt" in menu.screen


def test_a_new_folder_is_made_in_the_folder_shown(menu, files, media):
    menu.press("n", "2026", "enter", "enter")

    assert (media / "2026").is_dir()
    assert "2026/" in menu.screen


def test_deleting_asks_first_and_a_no_keeps_the_file(menu, files, media):
    menu.press("down", "down", "x", "n")
    assert (media / "logo.png").exists()
    assert menu.saw("Confirm") and menu.saw("logo.png on web-1?")

    menu.press("enter", "x", "y")
    assert not (media / "logo.png").exists()


def test_the_env_file_asks_for_the_password_before_it_is_downloaded(
    menu, application, project, local_host, here
):
    from dbs.manager.applications.repositories import ApplicationRepository

    ApplicationRepository().update(application, file_roots=[str(project)])
    screen = FilesScreen(menu.app, "web-1", "web-1")
    menu.app.push(screen)
    names = [entry.name for entry in screen.explorer.folder.entries]

    menu.press(*["down"] * names.index(".env"), "d", "s", PASSWORD, "enter")

    assert menu.saw("Password for sara")
    assert (here / ".env").read_bytes().startswith(b"SECRET_KEY=")


def test_a_folder_outside_what_the_application_allows_stays_closed(
    menu, application, local_host, tmp_path
):
    with pytest.raises(sources.Unreadable):
        ApplicationFiles(menu.app, "web-1", "web-1").list(str(tmp_path))


def test_a_name_with_an_escape_sequence_is_shown_and_never_sent(
    menu, application, media, local_host
):
    (media / "\x1b[2Jgone.txt").write_text("x")
    menu.app.push(FilesScreen(menu.app, "web-1", "web-1"))

    menu.press()

    assert "␛[2Jgone.txt" in menu.screen
    assert "\x1b[2J" not in menu.terminal.stream.getvalue().replace("\x1b[2J", "", 1)


def test_a_viewer_browses_and_is_offered_no_change(
    open_menu, django_user_model, admin, application, media, local_host
):
    from dbs.manager.accounts.services import AccountManagementService

    viewer = (
        AccountManagementService(None)
        .create(username="vera", password=PASSWORD, role="viewer")
        .user
    )
    menu = open_menu(viewer)
    menu.app.push(FilesScreen(menu.app, "web-1", "web-1"))

    menu.press("down", "down", "x", "u", "n", "d")

    assert (media / "logo.png").exists()
    hints = menu.screen.splitlines()[-1]
    assert "Upload" not in hints and "Delete" not in hints and "Download" not in hints
    assert "logo.png" in menu.screen


def test_this_computers_disk_is_listed_with_folders_first(here):
    (here / "b.txt").write_text("b")
    (here / "a").mkdir()
    (here / ".hidden").write_text("")

    folder = LocalDisk().list(None)

    assert folder.path == str(here) and folder.parent == str(here.parent)
    assert [entry.name for entry in folder.entries] == ["a", ".hidden", "b.txt"]
    assert [entry.kind for entry in folder.entries] == ["folder", "file", "file"]


def test_a_folder_this_account_cannot_read_says_so(tmp_path):
    with pytest.raises(sources.Unreadable, match="missing"):
        LocalDisk().list(str(tmp_path / "missing"))


def picked(menu, mode, *presses):
    dialog = PathDialog(menu.app, LocalDisk(), mode, "Choose")
    menu.queue(*presses)
    return menu.app.modal(dialog)


def test_choosing_a_file_takes_enter_on_a_file_and_opens_folders(menu, here):
    (here / "keys").mkdir()
    (here / "keys" / "id_ed25519").write_text("key")

    assert picked(menu, PICK_FILE, "enter", "enter") == str(
        here / "keys" / "id_ed25519"
    )


def test_choosing_a_folder_uses_the_one_shown(menu, here):
    (here / "exports").mkdir()

    assert picked(menu, PICK_FOLDER, "enter", "s") == str(here / "exports")
    assert picked(menu, PICK_FOLDER, "esc") is None


def test_a_target_is_a_folder_or_a_file_named_in_it(menu, here):
    assert picked(menu, PICK_TARGET, "s") == str(here)
    assert picked(menu, PICK_TARGET, "n", "export.dbs", "enter") == str(
        here / "export.dbs"
    )


def test_a_file_or_a_folder_can_be_the_one_selected(menu, here):
    (here / "media").mkdir()
    (here / "a.txt").write_text("a")

    assert picked(menu, PICK_ANY, "s") == str(here / "media")
    assert picked(menu, PICK_ANY, "down", "enter") == str(here / "a.txt")


def test_a_path_can_be_typed_instead(menu, here):
    assert picked(menu, PICK_FILE, "t", "/x", "enter") == f"{here}/x"


def test_the_list_filters_as_it_is_typed(menu, here):
    for name in ("alpha.txt", "beta.txt", "gamma.txt"):
        (here / name).write_text(name)

    assert picked(menu, PICK_FILE, "/", "bet", "enter", "enter") == str(
        here / "beta.txt"
    )


def test_sizes_are_written_for_a_person():
    assert explorer.size(None) == ""
    assert explorer.size(0) == "0 B"
    assert explorer.size(1536) == "1.5 KB"
    assert explorer.size(5 * 1024**3) == "5.0 GB"


def test_a_servers_folders_are_browsed_and_a_project_is_added_from_one(
    menu, make_server, local_host, project
):
    make_server("web-1", "10.0.0.5")
    (project / "manage.py").write_text("")
    screen = FoldersScreen(menu.app, "web-1", "web-1")
    menu.app.push(screen)
    screen.explorer.open(str(project.parent))

    menu.press("enter")
    assert screen.explorer.path == str(project)
    assert "manage.py" in menu.screen and "media/" in menu.screen

    menu.press("a")
    assert menu.app.top.collected()["--folder"] == str(project)
    assert menu.app.top.collected()["--server"] == "web-1"

import threading

from dbs.manager.shell.buffer import OutputBuffer


def test_a_reader_gets_what_was_written_from_its_cursor():
    buffer = OutputBuffer(1024)
    buffer.append(b"hello ")
    buffer.append(b"world")

    assert buffer.read(0, 0) == (b"hello world", 11, False)
    assert buffer.read(6, 0) == (b"world", 11, False)


def test_a_cursor_behind_what_is_kept_says_bytes_were_skipped():
    buffer = OutputBuffer(1024)
    buffer.append(b"abcdef")
    buffer.read(4, 0)

    assert buffer.read(1, 0) == (b"ef", 6, True)


def test_a_full_buffer_holds_the_writer_back_until_the_reader_catches_up():
    buffer = OutputBuffer(8)
    buffer.append(b"12345678")
    written = threading.Event()

    def more():
        buffer.append(b"9")
        written.set()

    writer = threading.Thread(target=more)
    writer.start()

    assert not written.wait(0.2)
    buffer.read(8, 0)
    assert written.wait(2)
    writer.join()
    assert buffer.read(8, 0) == (b"9", 9, False)


def test_a_waiting_reader_wakes_when_bytes_arrive():
    buffer = OutputBuffer(1024)
    threading.Timer(0.1, buffer.append, args=(b"late",)).start()

    assert buffer.read(0, 5) == (b"late", 4, False)


def test_a_closed_buffer_is_drained_once_its_bytes_are_read():
    buffer = OutputBuffer(1024)
    buffer.append(b"bye")
    buffer.close()

    assert not buffer.drained(0)
    assert buffer.read(0, 5) == (b"bye", 3, False)
    assert buffer.drained(3)
    assert buffer.append(b"more") is False

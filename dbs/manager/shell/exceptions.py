from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import APIException


class TerminalOff(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = "terminal_off"
    default_detail = "The terminal is switched off for this manager."


class TerminalNeedsAccount(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = "terminal_needs_account"
    default_detail = "A terminal opens only for a person signed in to the manager."


class TooManyTerminals(APIException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_code = "too_many_terminals"
    default_detail = "Close a terminal before opening another one."


class TerminalClosed(APIException):
    status_code = status.HTTP_410_GONE
    default_code = "terminal_closed"
    default_detail = "This terminal has closed."


class TerminalNotFound(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_code = "terminal_not_found"
    default_detail = "There is no such terminal open for you."

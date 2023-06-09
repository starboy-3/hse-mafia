from enum import Enum

class ExtendedEnum(Enum):

    @classmethod
    def list(cls):
        return list(map(lambda c: c.value, cls))

class Role(ExtendedEnum):
    KILLED = "killed"
    CIVILIAN = "civilian"
    MAFIA = "mafia"
    SHERIFF = "sheriff"

class Person:
    def __init__(self, role=None, name=None):
        self.role = role
        self.name = name


class Status(ExtendedEnum):
    DELETED = 'deleted'
    CONNECTED = 'connected'
    DISCONNECTED = 'disconnected'
    SUBSCRIBE = 'subscribe'

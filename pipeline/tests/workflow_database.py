"""Small async facade over mongomock, matching the Motor operations in V2."""


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def sort(self, *args):
        self.cursor = self.cursor.sort(*args)
        return self

    def limit(self, count):
        self.cursor = self.cursor.limit(count)
        return self

    async def to_list(self, length=None):
        return list(self.cursor)[:length]


class Collection:
    def __init__(self, raw):
        self.raw = raw

    def find(self, *args, **kwargs):
        return Cursor(self.raw.find(*args, **kwargs))

    def __getattr__(self, name):
        async def call(*args, **kwargs):
            return getattr(self.raw, name)(*args, **kwargs)

        return call


class Database:
    def __init__(self, raw):
        self.raw, self.name = raw, raw.name

    def __getitem__(self, name):
        return Collection(self.raw[name])

    def __getattr__(self, name):
        return self[name]


class Client:
    def __init__(self, raw):
        self.raw = raw

    def __getitem__(self, name):
        return Database(self.raw[name])

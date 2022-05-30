# type: ignore
__author__ = 'Lojack'

from typing import TYPE_CHECKING

import pytest

from decorators import Forwarder
if TYPE_CHECKING:
    from decorators import forward


class A:
    """Class for forwarding to for tests."""
    def __init__(self, a, b):
        self.a = a
        self._b = b
        self._d = {}

    def foo(self):
        return self.a

    @property
    def bar(self):
        return self._b
    @bar.setter
    def bar(self, value):
        self._b = value

    @property
    def full(self):
        try:
            return self._d['full']
        except KeyError:
            raise AttributeError
    @full.setter
    def full(self, value):
        self._d['full'] = value
    @full.deleter
    def full(self):
        try:
            del self._d['full']
        except KeyError:
            raise AttributeError

    def _no_get_setter(self, value): pass
    def _no_set_getter(self): return 1

    no_get = property(None, _no_get_setter)
    no_set = property(_no_set_getter)


class B(Forwarder[A]):
    foo = forward(A.foo)
    bar = forward(A.bar)
    full = forward(A.full)
    no_get = forward(A.no_get)
    no_set = forward(A.no_set)

    @forward.to(A.foo)
    def foobar(self):
        pass


def test_method():
    o = B(1,2)
    assert o.foo() == 1


def test_wrapping():
    a = A(1,2)
    o = B.wrap(a)
    assert o.resolve() is a


def test_wrap_error():
    with pytest.raises(TypeError):
        B.wrap(1)


def test_stub():
    o = B(1,2)
    assert o.foobar() == 1


class TestProperty:
    def test_no_deleter_property(self):
        o = B(1, 2)
        assert o.bar == 2
        o.bar = 3
        assert o.bar == 3
        with pytest.raises(AttributeError):
            del o.bar

    def test_full_property(self):
        o = B(1, 2)
        o.full = 1
        assert o.full == 1
        del o.full
        with pytest.raises(AttributeError):
            o.full
        with pytest.raises(AttributeError):
            del o.full

    def test_no_getter_property(self):
        o = B(1,2)
        with pytest.raises(AttributeError):
            o.no_get
        o.no_get = 1

    def test_no_setter_property(self):
        o = B(1,2)
        with pytest.raises(AttributeError):
            o.no_set = 1
        assert o.no_set == 1


def test_meta():
    class A:
        pass

    # `forward` should be removed from the class namespace if it wasn't
    # overridden
    class B(Forwarder[A]):
        pass
    with pytest.raises(AttributeError):
        B.forward

    # `forward` should not be removed from the class namespace, if it's not
    # overridden
    class C(Forwarder[A]):
        def forward(self):
            return 1
    o = C()
    assert o.forward() == 1
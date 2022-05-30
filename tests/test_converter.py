# type: ignore
__author__ = 'Lojack'


from typing import Union

import pytest

from decorators import ConversionWrapper


@pytest.fixture
def convert() -> ConversionWrapper:
    return_converters = {
        bool: str,
    }
    input_converters = {
        int: bool,
        float: int,
    }
    return ConversionWrapper(return_converters, input_converters)


@pytest.fixture
def converting_class():
    class A:
        def wrap_bool(self, value: bool) -> str:
            return str(value)
        
        def unwrap_boolstr(self, value: str) -> bool:
            return eval(value)

        def wrap_int(self, value: int) -> str:
            return str(value)

        convert = ConversionWrapper(
            {str: unwrap_boolstr},
            {bool: wrap_bool,
             int: wrap_int,
             float: int},
        )
    return A


def test_creation_error():
    with pytest.raises(TypeError):
        ConversionWrapper({int | str: bool})


class TestMethods:
    # Test using non-instance converters
    def test_noop(self, convert: ConversionWrapper):
        # Noop due to no args
        def method():
            return False
        assert convert(method) is method
        # Noop due to no annotations
        def method(a):
            return a
        assert convert(method) is method
        # Noop due to no matching annotations
        def method(a: str) -> float:
            return a
        assert convert(method) is method

    def test_string_signature(self, convert: ConversionWrapper):
        @convert.signature('(a: int) -> bool')
        def method(a):
            return a
        assert method(1) == 'True'

    def test_method_signature(self, convert: ConversionWrapper):
        @convert.signature
        def method(a: int) -> bool:
            pass
        @method
        def method(a):
            return a
        assert method(1) == 'True'

    def test_return_no_input(self, convert: ConversionWrapper):
        @convert
        def method(a) -> bool:
            return True
        assert method(0) == 'True'


class TestProperty:
    def test_annotations(self, convert: ConversionWrapper):
        class A:
            def __init__(self):
                self._a = True

            @property
            def a(self):
                return self._a
            @a.setter
            def a(self, value):
                self._a = value
        class B(A):
            a = convert.property(bool, int)(A.a)
            b = convert.property(bool)(A.a)
        o = B()
        assert o.a == 'True'
        o.a = 0
        assert o.a == 'False'
        o.b = True
        assert o.b == 'True'

    def test_noop(self, convert: ConversionWrapper):
        class A:
            # Both annotated, non-matching
            @property
            def a(self) -> int:
                return 1
            @a.setter
            def a(self, value: str):
                pass
            a = convert(a)

            # Both unannotated
            @convert
            @property
            def b(self):
                return 0

            def _set_c(self, value): pass
            c = convert(property(None, _set_c))

        o = A()
        assert o.a == 1


class TestUnbound:
    def test_methods(self, converting_class):
        convert = converting_class.convert
        class B(converting_class):
            def _impl(self, a, b):
                return (a,b)

            @convert
            def all_unbound(self, a: bool, b: bool) -> tuple[bool, bool]:
                return self._impl(a,b)

            @convert
            def mixed(self, a:bool, b: float) -> tuple[bool, float]:
                return self._impl(a,b)

            @convert
            def return_no_input(self) -> str:
                return 'False'

            @convert
            def return_with_input(self, a: bool) -> str:
                return 'True'
        o = B()
        assert o.all_unbound(True, False) == ('True', 'False')
        assert o.mixed(True, 1.5) == ('True', 1)
        assert o.return_no_input() is False
        assert o.return_with_input(False) is True

    def test_property(self, converting_class):
        convert = converting_class.convert
        class B(converting_class):
            @property
            def no_set(self) -> str:
                return 'True'
            no_set = convert(no_set)

            def _no_get_setter(self, value: bool):
                pass
            no_get = convert(property(None, _no_get_setter))
        o = B()
        assert o.no_set is True
        with pytest.raises(AttributeError):
            o.no_get
        o.no_get = False


class TestUnion:
    def test_noop(self, convert: ConversionWrapper):
        def method(a: Union[str, None]):
            return a
        assert method is convert(method)

    def test_new_style(self, convert: ConversionWrapper):
        @convert
        def method(a: int | float):
            return a
        assert method(1) is True
        assert method(1.5) == 1
        assert method('foo') == 'foo'
        
    def test_all(self, convert: ConversionWrapper):
        @convert
        def method(a: Union[int, float]):
            return a
        assert method(1) is True
        assert method(1.5) == 1
        assert method('foo') == 'foo'

    def test_some(self, convert: ConversionWrapper):
        @convert
        def method(a: Union[int, str]):
            return a
        assert method(1) is True
        method('foo') == 'foo'

    def test_unbound(self, converting_class):
        convert = converting_class.convert
        class B(converting_class):
            @convert
            def all_unbound(self, a: Union[int, bool]):
                return a
            
            @convert
            def mixed_unbound(self, a: Union[int, float]):
                return a
        o = B()
        assert o.all_unbound(1) == '1'
        assert o.all_unbound(True) == 'True'
        assert o.all_unbound('foo') == 'foo'
        assert o.mixed_unbound(1) == '1'
        assert o.mixed_unbound(1.5) == 1
        assert o.mixed_unbound('foo') == 'foo'

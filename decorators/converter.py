from __future__ import annotations


__author__ = 'Lojack'
__all__ = [
    'ConversionWrapper',
]


from collections.abc import Callable
from functools import cache, partial, wraps
import inspect
from inspect import Signature
import types
from typing import Any, get_args, get_origin, get_type_hints, TypeAlias, \
    TypeVar, Union


_UnionTypes = (Union,)
if hasattr(types, 'UnionType'): # pragma: no branch
    _UnionTypes = (Union, types.UnionType)
_BoundConversion: TypeAlias = Callable[[Any], Any]
_UnboundConversion: TypeAlias = Callable[[Any, Any], Any]
_Conversion: TypeAlias = _BoundConversion | _UnboundConversion
T = TypeVar('T')


class _TypeConverter:
    """Base class for all type converters."""
    def __call__(self, *args, **kwargs):
        raise NotImplementedError   # pragma: no cover


class _UnboundTypeConverter(_TypeConverter):
    """Base class used as a marker to note that a _TypeConverter uses one or
    more unbound instance methods in its conversion.
    """
    pass


class _UnionConverter(_TypeConverter):
    """A type converter that handles multiple types at once, with a different
    converter for each type. The converters are not unbound instance/class
    methods. If no matching converter is found, the value is return unchanged.
    """
    _converters: dict[type, _TypeConverter]

    def __init__(self, converters: dict[type, _Conversion]):
        self._converters = converters

    def __call__(self, value: Any) -> Any:
        for source_type, converter in self._converters.items():
            if isinstance(value, source_type):
                return converter(value)
        return value


class _UnboundUnionConverter(_UnionConverter, _UnboundTypeConverter):
    """A UnionConverter for which all conversion methods are unbound instance
       or class methods.
    """
    def __call__(self, instance: Any, value: Any) -> Any:
        for source_type, converter in self._converters.items():
            if isinstance(value, source_type):
                return converter(instance, value)
        return value


class _MixedUnionConverter(_UnionConverter, _UnboundTypeConverter):
    """A UnionConverter for which some conversion methods are unbound instance
       or class methods.
    """
    def __call__(self, instance: Any, value: Any) -> Any:
        for source_type, converter in self._converters.items():
            if isinstance(value, source_type):
                if isinstance(converter, _UnboundConverter):
                    return converter(instance, value)
                else:
                    return converter(value)
        return value


class _Converter(_TypeConverter):
    """A _TypeConverter which converts a type using a single argument function
    or type constructor.
    """
    _convert: _BoundConversion

    def __init__(self, converter: _Conversion) -> None:
        self._convert = converter

    def __call__(self, value: Any) -> Any:
        return self._convert(value)


class _UnboundConverter(_Converter, _UnboundTypeConverter):
    """A converter which converts a type using an unbound instance or class
    method.
    """
    _convert: _UnboundConversion

    def __call__(self, instance: Any, value: Any) -> Any:
        return self._convert(instance, value)


def _noop_converter(x: T) -> T:
    """Internal method used in two situations:
    1) Used to denote that no conversion is required.
    2) Used in _ArgsConverter to simplify the conversion loop for arguments
       that do not require conversion.
    """
    return x


class _TypeConverterFactory:
    """Machinery for managing all the type converters, and creating Union
    Converters on the fly.  Converters are accessed via type annotations.
    """
    _converters: dict[type, _TypeConverter]

    def __init__(self, converters: dict[type, _Conversion]):
        for annotation in converters:
            if self.is_union(annotation):
                raise TypeError(
                    f'Union type {annotation} is not supported as a single '
                    'converter.  Supply seperate converters for the underlying'
                    ' types.'
                )
        self._converters = {
            self.fixup_none(source_type): _UnboundConverter(converter)
                                          if self.is_two_arg(converter)
                                          else _Converter(converter)
            for source_type, converter in converters.items()
            if converter is not _noop_converter
        }

    @staticmethod
    def fixup_none(annotation: Any) -> Any:
        """None-types are usually annotated as `None`, however `None` is a
        constant of type `NoneType`.  Automatically convert `None`s to
        `NoneType`s so `issubclass` and `isinstance` checks work property on
        them.

        :param annotation: The annotation to potentially fix.
        :return: `NoneType` if the annotation is `None`, otherwise the
            annotation is returned unchanged.
        """
        if annotation is None:
            return type(None)
        return annotation

    @staticmethod
    def is_union(annotation: Any) -> bool:
        """Determine if an annotation is a union annotation (defined using
        either `Union[t1, ...]`, `t1 | ...`, or `Optional[t1]`).

        :param annotation: The type annotation to test.
        :return: True if the annotation is a union.
        """
        return get_origin(annotation) in _UnionTypes

    @staticmethod
    def is_two_arg(converter: _Conversion) -> bool:
        """Lazy way to determine if a callable is an unbound instance or class
        method.  Note this will falsely detect bare methods with two arguments
        as unbound class or instance methods.
        """
        try:
            sig = inspect.signature(converter)
            return len(sig.parameters) == 2
        except ValueError:
            # Classes are callable, but may have no signature
            # Also some third party libraries (wxPython...)
            # we can't get signatures from.
            return False

    @cache
    def create_union_converter(self, annotation: Any) -> _TypeConverter:
        """Create a _UnionConverter from a union type annotation.
        
        :annotation: A union type annotation.
        :return: A `_UnionConverter` for handling any of the matched types, or
            `_noop_converter` if no types match.
        """
        used_types = tuple(map(self.fixup_none, get_args(annotation)))
        used_converters = {
            source_type: converter
            for source_type, converter in self._converters.items()
            if any((issubclass(used_type, source_type)
                    for used_type in used_types))
        }
        if not used_converters:
            return _noop_converter
        unbound = list(map(self.is_two_arg, used_converters.values()))
        if all(unbound):
            # All unbound methods used for conversions
            return _UnboundUnionConverter(used_converters)
        elif any(unbound):
            # Some are bound, some are unbound
            return _MixedUnionConverter(used_converters)
        else:
            # All bound methods
            return _UnionConverter(used_converters)

    def get_type_converter(self, annotation: Any) -> _TypeConverter:
        """Get a _TypeConverter object for the given annotation, creating a new
        _UnionConverter if necessary for union annotations, getting a cached
        _TypeConverter for single types, or _noop_converter if no matching
        converter exists.

        :param annotation: Type annotation to get a converter for.
        :return: A type converter object for converting types specified in
            `annotation`.
        """
        annotation = self.fixup_none(annotation)
        if self.is_union(annotation):
            return self.create_union_converter(annotation)
        return self._converters.get(annotation, _noop_converter)


class _ArgsConverter:
    """Internal class which converts input values for a function."""
    _sig: Signature
    _conversions: dict[str, _TypeConverter]

    def __init__(self, sig: Signature, conversions: dict[str, _TypeConverter]):
        self._sig = sig
        self._conversions = conversions

    def __call__(self, *args, **kwargs):
        """Convert values in args and kwargs as determined by the target
        signature and converters.
        
        :return: (args, kwargs) with values converted.
        """
        bound = self._sig.bind(*args, **kwargs)
        arguments = bound.arguments
        # 'self' instance for unbound conversion methods
        instance = arguments.get('self', None)
        for name, converter in self._conversions.items():
            if isinstance(converter, _UnboundTypeConverter):
                arguments[name] = converter(instance, arguments[name])
            else:
                arguments[name] = converter(arguments[name])
        return bound.args, bound.kwargs


class ConversionWrapper:
    """Class for creating converted methods and properties.  Created with the
    desired conversion methods for both input types and output types.  Then use
    as a decorator on methods or properties that need conversions applied to
    them.  Supplied conversion methods may be normal functions, bound class or
    instance methods, or unbound class or instance methods.  In the case of
    unbound methods, the wrapped method is also assumed to be an unbound class
    or instance method.

    `ConversionWrapper`s cannot change the annotations on the converted method,
    so for this reason nesting them will have undefined results.
    
    Also note that when applied to a `property`, conversions are applied to the
    getters and setters that exist at that time.  For this reason, a property
    should only be converted after it is fully defined.  This normally should
    not be a problem: if the property is being defined in the a class which is
    also providing converted methods, then you have full control over the
    property itself and so should not need conversion.

    Examples::
        return_conversions = {
            int: str
        }
        input_conversions = {
            bool: str
        }
        convert = ConversionWrapper(return_conversion, input_conversions)

        @convert
        def foo(a: int) -> int:
            return a

        class A:
            @property
            def a(self) -> int:
                return 1
            @a.setter
            def a(self, value: int):
                pass
            a = convert(a)
    """
    def __init__(
            self,
            return_converters: dict[type, _Conversion] | None = None,
            input_converters: dict[type, _Conversion] | None = None,
        ) -> None:
        """Create a new wrapper utilizing the specified type converters.

        :param return_converters: A mapping of types to conversion methods to
            be used when the specified type is returned from a wrapped method.
        :param input_converters: A mapping of types to conversion methods to be
            used when the specified type is an input to a wrapped method.
        """
        self._return_converters = _TypeConverterFactory(return_converters)
        self._input_converters = _TypeConverterFactory(input_converters)

    def _get_callable_converters(
            self,
            signature: Signature
        ) -> tuple[_TypeConverter, _ArgsConverter | None]:
        """Used internally to create input and return type converters for a
        method, as determined by its signature.

        :param signature: The method signature object used to determine input
            and return types.
        :return: A tuple of (return_converter, input_converter), where
            `return_converter` is a type converter to apply to return values
            of the method, and `input_converter` is a callable to pass the
            arguments of the method into to be converted, returning the
            converted args and keyword args.
        """
        type_hints = signature.parameters
        conversions = {
            name: self._input_converters.get_type_converter(
                      parameter.annotation)
            for name, parameter in type_hints.items()
            if name != 'return'
        }
        if not conversions:
            input_converter = None
        elif all((converter is _noop_converter
                  for converter in conversions.values())):
            input_converter = None
        else:
            input_converter = _ArgsConverter(signature, conversions)
        return_annotation = signature.return_annotation
        return_converter = self._return_converters.get_type_converter(
            return_annotation)
        return return_converter, input_converter

    def convert_callable(
            self,
            method: Callable,
            signature: Signature | None = None
        ) -> Callable:
        """Create a new method which applies type conversions to input values
        and/or return values.  If a function signature is not supplied, it is
        introspected from the supplied method.

        :param method: The method to wrap.
        :param signature: If supplied, used to determine which type conversions
            are necessary for the supplied method.
        :return: A new method with the conversions specified, or the original
            method if no conversion are necessary.
        """
        if not signature:
            signature = inspect.signature(method, eval_str=True)
        print(f'Creating wrapper for {method}, using {signature!r}.')
        return_converter, input_converter = self._get_callable_converters(
            signature)
        if return_converter is _noop_converter:
            if not input_converter:
                # No conversions needed
                return method
            else:
                # Input conversion only
                @wraps(method)
                def wrapped(*args, **kwargs):
                    args, kwargs = input_converter(*args, **kwargs)
                    return method(*args, **kwargs)
        elif isinstance(return_converter, _UnboundTypeConverter):
            if not input_converter:
                # Return conversion only, using an unbound method
                @wraps(method)
                def wrapped(instance, *args, **kwargs):
                    return return_converter(instance, method(instance, *args, **kwargs))
            else:
                # Input and return conversion, using unbound methods
                @wraps(method)
                def wrapped(instance, *args, **kwargs):
                    args, kwargs = input_converter(instance, *args, **kwargs)
                    return return_converter(instance, method(*args, **kwargs))
        else:
            if not input_converter:
                # Return conversion only
                @wraps(method)
                def wrapped(*args, **kwargs):
                    return return_converter(method(*args, **kwargs))
            else:
                # Input and return conversions
                @wraps(method)
                def wrapped(*args, **kwargs):
                    args, kwargs = input_converter(*args, **kwargs)
                    return return_converter(method(*args, **kwargs))
        return wrapped

    def _get_property_converters(
            self,
            prop: property,
            get_annotation: Any = None,
            set_annotation: Any = None
        ) -> tuple[_TypeConverter, _TypeConverter]:
        """Used internally to create getter and setter type converter objects.

        :param prop: The property object to introspect `return_annotation` and
            `input_annotation` when not supplied.
        :param get_annotation: Type annotation assumed for the property getter.
        :param set_annotation: Type annotation assumed for the property setter.
        """
        if get_annotation is None:
            if (fget := prop.fget):
                get_annotation = get_type_hints(fget).get('return', None)
        get_converter = self._return_converters.get_type_converter(
            get_annotation)
        if set_annotation is None:
            if (fset := prop.fset):
                hints = get_type_hints(fset)
                hints.pop('return', None)
                if hints:
                    set_annotation = next(iter(hints.values()))
        set_converter = self._input_converters.get_type_converter(
            set_annotation)
        return (get_converter, set_converter)

    def convert_property(
            self,
            prop: property,
            get_annotation: Any = None,
            set_annotation: Any = None
        )-> property:
        """Create a new property object which applies type conversions to
        setters and getters.  If annotations are not explicitly supplied, they
        are introspected from the wrapped property object.

        :param prop: The property to wrap.
        :param get_annotation: The return type expected from the wrapped
            property. Used to look up which conversion method to use on the
            property getter.
        :param set_annotation: The type expected for values passed to the
            wrapped property. Used to look up which conversion method to use on
            the property setter.
        :return: A new property with the conversions specified, or the original
            property if no conversion are necessary.
        """
        get_converter, set_converter = self._get_property_converters(
            prop, get_annotation, set_annotation)
        if not (fget := prop.fget) or get_converter is _noop_converter:
            # No conversion needed on getter
            getter = fget
        elif isinstance(get_converter, _UnboundTypeConverter):
            # Convert on getter result with an unbound method
            @wraps(fget)
            def getter(instance):
                return get_converter(instance, fget(instance))
        else:
            # Convert on getter result with normal method
            @wraps(fget)
            def getter(instance):
                return get_converter(fget(instance))
        if not (fset := prop.fset) or set_converter is _noop_converter:
            # No conversion needed on setter
            setter = fset
        elif isinstance(set_converter, _UnboundTypeConverter):
            # Convert on setter with an unbound method
            @wraps(fset)
            def setter(instance, value):
                fset(instance, set_converter(instance, value))
        else:
            # Convert on setter with a normal method
            @wraps(fset)
            def setter(instance, value):
                fset(instance, set_converter(value))
        if getter is not fget or setter is not fset:
            return property(getter, setter, prop.fdel, prop.__doc__)
        else:
            return prop

    def __call__(
            self,
            method_or_prop: Callable | property
        ) -> Callable | property:
        """Wrap a method or property with conversions to the return types
        and input types.

        :param method_or_prop: Method or property to wrap.  Type annotations
            for determining what conversions are needed are introspected.
        :return: A new method or property with input and output conversions.
        """
        if isinstance(method_or_prop, property):
            return self.convert_property(method_or_prop)
        else:
            return self.convert_callable(method_or_prop)

    def property(
            self,
            get_annotation: Any,
            set_annotation: Any = None
        ) -> Callable:
        """Specify the getter and setter type annotations for a property.  If
        no setter annotation is supplies, the getter annotation is assumed to
        apply to both getting and setting the property.  This can be used for
        library properties that are either unannotated, or cannot be otherwise
        introspected.

        :param get_annotation: The type annotation to use for the property
            setter.
        :param set_annotation: The type annotation to use for the property
            getter.  If not supplied, assumed the same as `return_annotation`.
        :return: A wrapper to apply to a property.

        Example::
            convert = ConversionWrapper(...)
        
            class Foo:
                @convert.property(int)
                @property
                def a(self):
                    return 1
        """
        set_annotation = set_annotation or get_annotation
        return partial(
            self.convert_property,
            get_annotation=get_annotation,
            set_annotation=set_annotation
        )

    def signature(self, method_or_str: Callable | str) -> Callable:
        """Sepecify a function signature to use for the converted method.
        The signature can be specified in either string form or via a second
        method.  This can be used to supply type annotations to library methods
        that are either unannotated, or annotations cannot be otherwise
        introspected.

        :param method_or_str: Either a method or a signature string.
        :return: A wrapper to apply to a method.

        Example::
            @convert.signature('(a: int) -> str')
            def to_be_converted(a):
                return str(a)
            
            @convert.signature
            def convert_sig(a: int) -> str:
                pass
            @convert_sig
            def to_be_converted(a):
                return str(a)
        """
        if isinstance(method_or_str, str):
            # Handle string specified signatures
            globs = globals()
            locals = {}
            code = f'def foo{method_or_str}: pass'
            exec(code, globs, locals)
            method_or_str: Callable = locals['foo']
        signature = inspect.signature(method_or_str, eval_str=True)
        return partial(self.convert_callable, signature=signature)

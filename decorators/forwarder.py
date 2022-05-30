from __future__ import annotations


__author__ = 'Lojack'
__all__ = [
    'AForwarder',
    'Forwarder',
    'forward',
]


from functools import wraps
from typing import Any, Callable, Generic, get_args, TypeVar

try:
    # py 3.9+
    from functools import cache
except ImportError: # pragma: no cover
    from functools import lru_cache as cache


class ForwardWrapper:
    """Wrapper object for wrapping methods to be forwarded to a different
    object.  A resolver is used to get the object to forward to.
    """
    _resolve: Callable[[Any], Any]

    def __init__(self, resolver: Callable[[Any], Any]) -> None:
        """Create the wrapper.
        
        :param resolver: Method used to get the object to forward to.
        """
        self._resolve = resolver

    def wrap_property(self, prop: property) -> property:
        """Create a new property which forwards its getter, setter, and deleter
        to the forwarded object.

        :param prop: The property object on the forwarded class.
        :return: A new property which forwards to `prop`.
        """
        fget, fset, fdel = prop.fget, prop.fset, prop.fdel
        resolve = self._resolve
        if fget:
            @wraps(fget)
            def getter(instance) -> Any:
                return fget(resolve(instance))
        else:
            getter = None   # type: ignore
        if fset:
            @wraps(fset)
            def setter(instance, value: Any) -> None:
                fset(resolve(instance), value)
        else:
            setter = None   # type: ignore
        if fdel:
            @wraps(fdel)
            def deleter(instance) -> None:
                fdel(resolve(instance))
        else:
            deleter = None  # type: ignore
        return property(getter, setter, deleter, prop.__doc__)

    def wrap_method(self, method: Callable) -> Callable:
        """Create a new function which forwards to the unbound `method` on the
        forwarded object.
        
        :param method: Unbound method on the forwarded class.
        :return: A new method which forwards to `method`.
        """
        resolve = self._resolve
        @wraps(method)
        def wrapped(instance, *args, **kwargs):
            return method(resolve(instance), *args, **kwargs)
        return wrapped
    
    def __call__(
        self,
        method_or_prop: Callable | property
    ) -> Callable | property:
        """Create a forwarded method or property.
        
        :param method_or_prop: The unbound method or property on the forwarded
            class to forward to.
        :return: A new method or property forwarding to `method_or_prop`.
        """
        if isinstance(method_or_prop, property):
            return self.wrap_property(method_or_prop)
        else:
            return self.wrap_method(method_or_prop)

    def to(self, method: Callable) -> Callable[[Callable], Callable]:
        """Create a forwarding wrapper.  This form allows for supplying a
        `stub` method on the parent class for type-checkers.
        
        :param method: The method to forward to.
        :return: A wrapper that returns the forwarder to `method`, rather than
            the method the wrapper is applied to.

        Example::
            @forward.to(target_method)
            def my_method(a: int) -> bool:
                pass
        """
        def wrapper(_func: Callable) -> Callable:
            return self(method) # type: ignore
        return wrapper


C = TypeVar('C', bound='Forwarder')
T = TypeVar('T')


class AForwarder(Generic[T]):
    """Base class for classes which wish to forward to another class.
    
    Example::

    forward = ForwardWrapper(AForwarder.resolve)

    class A:
        def foo(self):
            print('foo!')
    
    class B(AForwarder[A]):
        foo = forward(A.foo)    
    """
    _wrapped_object: T

    @classmethod
    @cache
    def _wrapped_type(cls: type[C]) -> type[T]: # type: ignore
        """Get the generic type `T` this class was created with."""
        # NOTE: This is hacky in that it relies on internal details of the
        # `typing` module.
        generic = cls.__orig_bases__[0]     # type: ignore
        return get_args(generic)[0]

    def __init__(self, *args, **kwargs) -> None:
        """Initialize by either creating a new `_wrapped_object` instance,
        or wrapping an existing one.  Wrapping an existing instance should
        be accomplished via the `wrap` class method.
        """
        wrapped_type = self._wrapped_type()
        if (instance := kwargs.pop('_do_wrap', False)):
            if not isinstance(instance, wrapped_type):
                raise TypeError(
                    f'Forwarder for type {wrapped_type} cannot wrap {instance} '
                    f'of type {type(instance)}.'
                )
            self._wrapped_object = instance
        else:
            self._wrapped_object = wrapped_type(*args, **kwargs)

    def resolve(self) -> T:
        return self._wrapped_object

    @classmethod
    def wrap(cls: type[C], to_wrap_instance: Any) -> C: # type: ignore
        return cls(_do_wrap=to_wrap_instance)


forward = ForwardWrapper(AForwarder.resolve)


class _ForwarderMeta(type):
    """Metaclass to inject the `forward` object into the class construction
    namespace of `Forwarder` objects.
    """
    @classmethod
    def __prepare__(cls, name, bases) -> dict:
        # Inject `forward` into the namespace
        return {'forward': forward}

    def __new__(cls, name, bases, classdict):
        # Remove `forward` from the class namespace after class creation
        if classdict.get('forward', None) is forward:
            del classdict['forward']
        return type.__new__(cls, name, bases, classdict)


class Forwarder(AForwarder[T], metaclass=_ForwarderMeta):
    """Version of AForwarder that uses a metaclass to inject the ForwardWrapper
    instance `forward` into the class namespace, for use during class creation.

    Example::

    class A:
        def foo(self):
            print('foo!')
    
    class B(Forwarder[A]):
        # Note: no need to create `forward` first
        foo = forward(A.foo)
    """
    pass

# SPDX-License-Identifier: MIT
"""Finite stored-field access for explicitly source-declared native classes.

No property, serializer, custom attribute lookup or metaclass equality runs.
Runtime class registration is acquisition plumbing; original-source controls
must separately qualify how native code consumes these stored fields.
"""
import sys
from types import GetSetDescriptorType, MappingProxyType, ModuleType

from .api import InvalidEvidence,canonical,digest
from ._telemetry_protocol import PrimitiveError

_NAMESPACE=type.__dict__['__dict__']
_MRO=type.__dict__['__mro__']
_QUALNAME=type.__dict__['__qualname__']


def namespace(cls):
    try:
        value=_NAMESPACE.__get__(cls)
    except TypeError as exc:
        raise InvalidEvidence('Native record registration requires a class') from exc
    if any(type(key) is not str for key in value):
        raise InvalidEvidence('Native class namespace requires exact string keys')
    return value


def shape(cls):
    return tuple((key,id(value)) for key,value in sorted(namespace(cls).items()))


class RecordRegistry:
    __slots__=('_records','binding_sha256','policy_sha256')

    def __init__(self,declarations,classes,*,binding_sha256,policy_sha256):
        canonical(declarations)
        if type(classes) is not dict or any(type(k) is not str for k in classes) or set(classes)!=set(declarations):
            raise InvalidEvidence('Native record classes must match declared types')
        entries={}
        for ident,spec in declarations.items():
            cls=classes[ident];ns=namespace(cls)
            name=_QUALNAME.__get__(cls)
            if (type(ns.get('__module__')) is not str or type(name) is not str
                    or ns['__module__']!=spec['module'] or name!=spec['name']):
                raise InvalidEvidence('Native record class identity mismatch')
            module=sys.modules.get(spec['module'])
            if (type(module) is not ModuleType or
                    ModuleType.__dict__['__dict__'].__get__(module).get(spec['name']) is not cls):
                raise InvalidEvidence('Native record class is not the loaded declared class')
            mro=_MRO.__get__(cls)
            descriptor=None
            for parent in mro:
                attrs=namespace(parent)
                if any(field in attrs for field in spec['fields']):
                    raise InvalidEvidence('Native record fields must be stored, not class attributes/descriptors')
                if descriptor is None and '__dict__' in attrs:
                    candidate=attrs['__dict__']
                    if (type(candidate) is not GetSetDescriptorType
                            or candidate.__name__!='__dict__'
                            or candidate.__objclass__ is not parent):
                        raise InvalidEvidence('Native record has an unqualified instance dictionary')
                    descriptor=candidate
            if descriptor is None:
                raise InvalidEvidence('Native record has no native instance dictionary')
            entries[ident]=(cls,tuple(spec['fields']),descriptor,
                            tuple((base,shape(base)) for base in mro))
        object.__setattr__(self,'_records',MappingProxyType(entries))
        object.__setattr__(self,'binding_sha256',binding_sha256)
        object.__setattr__(self,'policy_sha256',policy_sha256)

    def __setattr__(self,name,value):
        raise AttributeError('Native record registry is immutable')

    def read(self,value,ident,field):
        if ident not in self._records:
            raise PrimitiveError('Unregistered native record type')
        cls,fields,descriptor,bases=self._records[ident]
        if type(value) is not cls or field not in fields:
            raise PrimitiveError('Native record type/field outside declaration')
        current_mro=_MRO.__get__(cls)
        if (len(current_mro)!=len(bases)
                or any(current is not saved[0]
                       for current,saved in zip(current_mro,bases))):
            raise PrimitiveError('Native record inheritance changed after registration')
        try:
            changed=any(shape(base)!=expected for base,expected in bases)
        except InvalidEvidence as exc:
            raise PrimitiveError('Native record class namespace changed') from exc
        if changed:
            raise PrimitiveError('Native record class changed after registration')
        try:
            data=descriptor.__get__(value,cls)
        except TypeError as exc:
            raise PrimitiveError('Native record storage descriptor no longer applies') from exc
        if type(data) is not dict or any(type(k) is not str for k in data):
            raise PrimitiveError('Native record storage is not an exact string-keyed dictionary')
        if field not in data:
            raise PrimitiveError('Native stored field is absent')
        return data[field]


def register_records(profile,binding,classes):
    from .binding import validate_binding
    validate_binding(profile,binding)
    if binding['grammar_version'] not in {'1.3.0','1.4.0'} or not profile.get('record_types'):
        raise InvalidEvidence('Native records require opt-in grammar 1.3 declarations')
    return RecordRegistry(profile['record_types'],classes,
                          binding_sha256=binding['sha256'],policy_sha256=digest(profile))

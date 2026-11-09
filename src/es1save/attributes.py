# Copyright (C) 2026 KiasuBurger
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""The attributes of an item, with its mods, calculated as the game calculates them.

The game shows an item's attributes in the equipment screen. For each attribute in the
item's EquipmentAttributes, it calls GetEquipmentAttributeValue on the item, and shows the
attribute if the call returns true. A mod changes the item when it is installed: its OnInstall
changes the values of the item, for example the WeaponConfig of a weapon.

Many items and all mods do this in blueprint code. This module runs that code (read by
kismet.py into the game data) on a copy of the item's values. The parts that the game does in
C++ are written here from the game's executable:

    AWeaponBase, AWeaponProjectile, ADeviceBase, AShieldBase   GetEquipmentAttributeValue
    AModBase                                                   OnInstall
    the constructors                                           the values that a blueprint
                                                               does not set (NATIVE_DEFAULTS)
    AllAttributesDisplayInfo                                   the name, format and better
                                                               direction of each attribute
    FAttribute::RefreshValue                                   the critical hit chance

The equipment screen (LIB_F_WidgetHelper.RefreshEquipmentAttributesList) shows a value with
up to 2 decimals, rounded half to even, with grouping. Range, Velocity and Area Damage Range
have no decimals. It compares each value with the value of the item's class default object,
which has no mods and no player ship.

    rows(game, path, mods, seeds, crit_chance, ship)   the rows of the item's attributes
    mod_rows(game, path, seed)                         the rows of a mod's own attributes

A blueprint function that uses something this module does not know raises Unsupported, and
the attribute is left out.
"""

import copy
import math
import struct
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from .gamedata import GameData

# EEquipmentAttribute, in order: (name, the name and format that the game shows, whether a
# lower value is better). From AllAttributesDisplayInfo, which the AEquipmentBase constructor
# fills with the English texts of the game's C++ code. The game's .locres has an older format
# for some of them, for example '{0}' for the spread where the game shows '{0}°'.
ATTRIBUTES = [
    ('AreaDamageRange', 'Area Damage Range', '{0}m', False),
    ('ChargeDuration', 'Full Charge Duration', '{0}s', True),
    ('ConversionAmount', 'Conversion Amount', '{0}', False),
    ('ConversionPercent', 'Conversion Percentage', '{0}%', False),
    ('ConversionRatio', 'Conversion Ratio', '{0}', False),
    ('CoolDownDuration', 'Cool Down Duration', '{0}s', True),
    ('CoolDownDurationDecreasePercent', 'Cool Down Duration', '-{0}%', True),
    ('CrititcalHitChance', 'Critical Hit Chance', '{0}%', False),
    ('CrititcalHitChanceIncreasePercent', 'Critical Hit Chance', '+{0}%', False),
    ('CriticalHitDamageMultiplier', 'Critical Hit Damage Bonus', '{0}x', False),
    ('DamageIncreasePercent', 'Damage', '+{0}%', False),
    ('DamagePerEnergy', 'Damage Per Energy', '{0}', False),
    ('MaxEnergyPercent', 'Energy Capacity', '{0}%', True),
    ('EnergyAllocation', 'Energy Allocation', '{0}', True),
    ('EnergyConsumption', 'Energy Consumption', '{0}', True),
    ('EnergyConsumptionDecreasePercent', 'Energy Consumption', '-{0}%', False),
    ('EnergyConsumptionIncreasePercent', 'Energy Consumption', '+{0}%', True),
    ('EnergyConsumptionPerSecond', 'Energy Consumption', '{0}/s', True),
    ('EnergyRechargeRateDecreasePercent', 'Energy Recharge Rate', '-{0}%', True),
    ('EffectDecreasePercent', 'Effect', '-{0}%', False),
    ('EffectDuration', 'Effect Duration', '{0}s', False),
    ('EffectDurationIncreasePercent', 'Effect Duration', '+{0}%', False),
    ('EffectIncreaseAdd', 'Effect', '+{0}', False),
    ('EffectIncreaseFactor', 'Effect', '{0}x', False),
    ('EffectIncreasePercent', 'Effect', '+{0}%', False),
    ('FireRate', 'Fire Rate', '{0}/s', False),
    ('FireRateIncreasePercent', 'Fire Rate', '+{0}%', False),
    ('FullChargeAddtionalProjectiles', 'Full Charge Add. Projectiles', '{0}', False),
    ('FullChargeDamageMultiplier', 'Full Charge Damage Bonus', '{0}x', False),
    ('HomingAbility', 'Homing', 'Yes', False),
    ('HullDamage', 'Hull Damage', '{0}', False),
    ('HullDamagePerSecond', 'Hull DPS', '{0}/s', False),
    ('JumpChargeIncreasePercent', 'Jump Charge Duration', '+{0}%', True),
    ('JumpCoolDownIncreasePercent', 'Jump Cool Down Duration', '+{0}%', True),
    ('LifeTime', 'Life Time', '{0}s', False),
    ('NanoBotDropChance', 'Nano Bots Drop Chance', '{0}%', False),
    ('Range', 'Range', '{0}m', False),
    ('RangeIncreasePercent', 'Range', '+{0}%', False),
    ('RequiredFuelDecreasePercent', 'Required Fuel', '-{0}%', False),
    ('ResourceAmount', 'Resource Amount', '{0}', False),
    ('ShieldDamage', 'Shield Damage', '{0}', False),
    ('ShieldDamagePerSecond', 'Shield DPS', '{0}/s', False),
    ('ShieldHitpoints', 'Hitpoints', '{0}', False),
    ('ShieldHitpointsIncreasePercent', 'Hitpoints', '+{0}%', False),
    ('ShieldPiercing', 'Shield Piercing', '{0}%', False),
    ('ShieldPiercingIncreasePercent', 'Shield Piercing', '+{0}%', False),
    ('ShieldRechargeDelayAfterHit', 'Recharge Delay', '{0}s', True),
    ('ShieldRechargeDelayAfterHitDecreasePercent', 'Recharge Delay', '-{0}%', True),
    ('ShieldRechargePerSecond', 'Recharge Rate', '{0}/s', False),
    ('ShieldRechargePerSecondIncreasePercent', 'Recharge Rate', '+{0}%', False),
    ('ShieldShutdownDuration', 'Shutdown Duration', '{0}s', True),
    ('ShieldShutdownDurationDecreasePercent', 'Shutdown Duration', '-{0}%', True),
    ('Speed', 'Velocity', '{0}m/s', False),
    ('SpeedDecreasePercent', 'Speed', '-{0}%', False),
    ('SpeedIncreasePercent', 'Velocity', '+{0}%', False),
    ('SpreadDecreasePercent', 'Spread', '-{0}%', False),
    ('SpreadDegrees', 'Spread', '{0}°', True),
    ('SuccessChance', 'Success Chance', '{0}%', False),
    ('MaxSpeedIncreasePercent', 'Max Speed', '+{0}%', False),
    ('MaxSpeedDecreasePercent', 'Max Speed', '-{0}%', True),
    ('RepairAmount', 'Repair Amount', '{0}', False),
]
ATTRIBUTE_INDEX = {name: i for i, (name, _, _, _) in enumerate(ATTRIBUTES)}
HOMING = ATTRIBUTE_INDEX['HomingAbility']
# the attributes that the equipment screen shows without decimals
WHOLE = {ATTRIBUTE_INDEX['Speed'], ATTRIBUTE_INDEX['AreaDamageRange'], ATTRIBUTE_INDEX['Range']}
SHIP_CLASSES = ['Interceptor', 'Scout', 'Gunship', 'TechFighter']
SHIP_CLASS_KEYS = ['INTERCEPTOR', 'SCOUT', 'GUNSHIP', 'TECHFIGHTER']

ENUMS = {
    'EEquipmentAttribute': [name for name, _, _, _ in ATTRIBUTES],
    'EDeviceType': ['Active', 'Passive'],
    'EShipClass': [*SHIP_CLASSES, 'Undefined'],
    'EEquipmentType': ['Consumable', 'Device', 'PrimaryWeapon', 'SecondaryWeapon', 'Mod', 'Any', 'Buff', 'None'],
    'EAttributeOp': ['Add', 'Multiply', 'Set', 'Invalid'],
}

# The C++ parent of each C++ class that a blueprint of an item can have.
NATIVE_PARENTS = {
    'WeaponInstantHit': 'WeaponBase',
    'WeaponProjectile': 'WeaponBase',
    'WeaponBase': 'EquipmentBase',
    'ShieldBase': 'DeviceBase',
    'DeviceBase': 'EquipmentBase',
    'ConsumableDeployDroneBase': 'ConsumableBase',
    'ConsumableBase': 'EquipmentBase',
    'ModBase': 'EquipmentBase',
    'BuffBase': 'EquipmentBase',
}


def _attribute_struct() -> dict[str, Any]:
    return {'BaseValue': 0.0, 'CurrentValue': 0.0, 'Modifiers': [], 'isDirty': True}


# The values that the C++ constructors set, for the values that no blueprint sets. The rest of
# an object starts as zero.
NATIVE_DEFAULTS: dict[str, dict[str, Any]] = {
    'WeaponBase': {
        'MaxAmmoPerSlot': 1,
        'WeaponConfig': {
            'TimeBetweenShots': 0.2,
            'HullDamage': 10.0,
            'ShieldDamage': 10.0,
            'RadialDamageRadius': 100.0,
            'Range': 200000.0,
            'Speed': 100000.0,
            'AdditionalProjectilesSpreadDegrees': 5.0,
            'ShotsPerBurst': 1,
            'BurstDelay': 0.067,
            'bDealDirectDamage': True,
        },
        'CriticalHitChanceAddAmount': _attribute_struct(),
    },
    'ShieldBase': {
        'DeviceType': 1,  # passive
        'EnergyConsumption': 10.0,
        'MaxHitpoints': 100.0,
        'RechargePerSecond': 25.0,
        'RechargeDelayAfterHit': 4.0,
        'ShutDownDuration': 8.0,
    },
    'ConsumableBase': {'MaxAmountPerSlot': 1, 'CoolDown': 1.0},
}

STEP_LIMIT = 200000


class Unsupported(Exception):
    """The code uses something that this module cannot run."""


def f32(value: float) -> float:
    """The value as a 32-bit float, as the game stores it."""
    try:
        return float(struct.unpack('<f', struct.pack('<f', value))[0])
    except OverflowError:
        return math.copysign(math.inf, value)


def _enum(value: Any) -> Any:
    """An enum value 'EType::Name' as its number, when the type is known here."""
    if isinstance(value, str) and '::' in value:
        kind, _, name = value.partition('::')
        names = ENUMS.get(kind)
        if names and name in names:
            return names.index(name)
        raise Unsupported('the enum %s' % value)
    return value


def _number(value: Any) -> float:
    value = _enum(value)
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return 0.0
    raise Unsupported('a number from %r' % (value,))


class Cls:
    """A class, as GetObjectClass returns it."""

    def __init__(self, path: str) -> None:
        self.path = path


class Library:
    """The default object of a C++ function library, on which blueprints call functions."""

    def __init__(self, name: str) -> None:
        self.name = name


class Native:
    """A C++ object that the code reads from: the game instance and its perk collection."""

    def __init__(self, props: dict[str, Any], methods: dict[str, Any]) -> None:
        self.props = props
        self.methods = methods


# the perks that the code of the items reads, by the getter of UPerkCollection that reads each
PERK_GETTERS = {
    'GetRepairHitpointsAmountPerNanobot': 'Hitpoint repair amount per nanobot',
    'GetCriticalHitChanceMod': 'Critical hit chance',
}


class Obj:
    """An item or a mod: its class and a copy of its values."""

    def __init__(self, vm: VM, path: str) -> None:
        self.vm = vm
        self.path = path
        self.chain = vm.chain(path)  # the blueprint classes, from this one to the top
        self.natives = vm.natives(path)  # the C++ classes, from the nearest to EquipmentBase
        self.props = vm.defaults(path)
        self.player = False  # whether the object is on the player's ship (not a class default)

    def names(self) -> set[str]:
        out = {p.rsplit('.', 1)[-1] for p in self.chain}
        return out | set(self.natives)


class Frame:
    def __init__(self, obj: Obj, cls: str) -> None:
        self.obj = obj
        self.cls = cls  # the class whose code runs, for its own functions
        self.vars: dict[str, Any] = {}


@dataclass
class Row:
    attribute: str  # the EEquipmentAttribute name, or '' for the class restriction
    name: str  # as the game shows it, in capitals
    text: str  # the value, formatted as the game formats it
    value: float | None
    state: str  # 'better', 'worse', or ''


class VM:
    def __init__(self, game: GameData, perks: dict[str, float] | None = None) -> None:
        """perks: the value of each perk of the pilot, by its ID, as profile.perk_value
        gives it."""
        self.game = game
        self.classes = game.classes
        self.by_name = {p.rsplit('.', 1)[-1]: p for p in self.classes}
        self.perks = perks or {}
        # the critical hit chance of the weapon component of the player's ship
        self.crit_chance = self.perks.get('Critical hit chance', 0.0)
        collection = Native({}, {getter: self._perk_getter(perk) for getter, perk in PERK_GETTERS.items()})
        self.game_instance = Native({'PerkCollection': collection}, {})
        self.steps = 0

    def _perk_getter(self, perk: str) -> Any:
        return lambda args: self.perks.get(perk, 0.0)

    # ---- classes

    def chain(self, path: str) -> list[str]:
        out = []
        current: str | None = path
        while current and current in self.classes and current not in out:
            out.append(current)
            current = self.by_name.get(self.classes[current].get('parent') or '')
        return out

    def natives(self, path: str) -> list[str]:
        chain = self.chain(path)
        top = self.classes[chain[-1]].get('parent') if chain else None
        out = []
        while top and top not in out:
            out.append(top)
            top = NATIVE_PARENTS.get(top)
        return out

    def defaults(self, path: str) -> dict[str, Any]:
        props: dict[str, Any] = {}
        for native in reversed(self.natives(path)):
            _merge(props, copy.deepcopy(NATIVE_DEFAULTS.get(native, {})))
        for cls in reversed(self.chain(path)):
            _merge(props, copy.deepcopy(self.classes[cls].get('values', {})))
        return props

    def instance(self, path: str) -> Obj:
        if path not in self.classes:
            raise Unsupported('no code for %s' % path)
        return Obj(self, path)

    # ---- calls

    def find(self, obj: Obj, name: str, start: str | None = None) -> tuple[str, dict[str, Any]] | None:
        """The blueprint function `name` of the object, from class `start` upwards."""
        chain = obj.chain
        if start is not None:
            short = [p.rsplit('.', 1)[-1] for p in chain]
            if start not in short:
                return None
            chain = chain[short.index(start) :]
        for cls in chain:
            function = self.classes[cls].get('functions', {}).get(name)
            if function:
                return cls, function
        return None

    def call_method(self, obj: Obj, name: str, args: list[Any], start: str | None = None) -> tuple[Any, list[Any]]:
        """Calls a function of the object with the values of its parameters. Returns the
        return value and the values of all parameters after the call."""
        found = self.find(obj, name, start)
        if found:
            return self.run(obj, found[0], name, found[1], args)
        for native in obj.natives:
            method = NATIVE_METHODS.get((native, name))
            if method:
                return method(self, obj, args)
        if name in ('Activate', 'Deactivate', 'ReceiveBeginPlay'):
            return True, [None] * len(args)
        raise Unsupported('the function %s of %s' % (name, obj.path))

    def run(self, obj: Obj, cls: str, name: str, function: dict[str, Any], args: list[Any]) -> tuple[Any, list[Any]]:
        """Runs a blueprint function. Returns its return value, and the value of each out
        parameter (None for the other parameters)."""
        frame = Frame(obj, cls)
        params = function.get('params', [])
        for (param, _out), value in zip(params, args, strict=False):
            frame.vars[param] = value
        code = function['code']
        at = {offset: i for i, (offset, _) in enumerate(code)}
        pc = 0
        if name.startswith('ExecuteUbergraph'):  # the event graph starts where the event is
            pc = at.get(int(_number(args[0])) if args else 0, 0)
        flow: list[int] = []
        while pc < len(code):
            self.steps += 1
            if self.steps > STEP_LIMIT:
                raise Unsupported('too many steps')
            node = code[pc][1]
            op = node[0]
            if op == 'jump':
                pc = at[node[1]]
                continue
            if op == 'jumpifnot':
                pc = pc + 1 if self.eval(node[2], frame) else at[node[1]]
                continue
            if op == 'push':
                flow.append(node[1])
            elif op == 'pop':
                if not flow:
                    break
                pc = at[flow.pop()]
                continue
            elif op == 'popifnot':
                if not self.eval(node[1], frame):
                    if not flow:
                        break
                    pc = at[flow.pop()]
                    continue
            elif op == 'computedjump':
                pc = at[int(self.eval(node[1], frame))]
                continue
            elif op == 'return':
                self.eval(node[1], frame)
                break
            elif op == 'end':
                break
            else:
                self.eval(node, frame)
            pc += 1
        return frame.vars.get('ReturnValue'), [frame.vars.get(p) if out else None for p, out in params]

    def call(self, node: list[Any], frame: Frame, target: Any) -> Any:
        """A call node, made on `target` (an Obj, a Library, or None for the frame's object)."""
        kind, ref, argnodes = node
        name = ref.rsplit('.', 1)[-1] if ref else ''
        owner = ref.rsplit('.', 1)[0] if ref and '.' in ref else ''
        if isinstance(target, Library) or owner in LIBRARIES:
            library = target.name if isinstance(target, Library) else owner
            function = LIBRARY_FUNCTIONS.get(name)
            if function is None:
                raise Unsupported('the library function %s.%s' % (library, name))
            return function(self, frame, argnodes)
        if isinstance(target, Native):
            method = target.methods.get(name)
            if method is None:
                raise Unsupported('the C++ function %s' % name)
            return method([self.eval(a, frame) for a in argnodes])
        obj = target if isinstance(target, Obj) else frame.obj
        args = [self.eval(a, frame) for a in argnodes]
        if kind == 'vcall':
            result, after = self.call_method(obj, name, args)
        elif owner.endswith('_C'):
            result, after = self.call_method(obj, name, args, start=owner)
        elif owner:  # a C++ function, which calls the C++ implementation of the object
            result, after = self._native(obj, name, args)
        else:  # a function of the class whose code runs
            found = self.classes[frame.cls].get('functions', {}).get(name)
            if found is None:
                raise Unsupported('the function %s' % name)
            result, after = self.run(obj, frame.cls, name, found, args)
        for argnode, value in zip(argnodes, after, strict=False):
            if value is not None and argnode[0] in ('local', 'self', 'member', 'ctx'):
                try:
                    self.assign(argnode, value, frame)
                except Unsupported:
                    pass
        return result

    def _native(self, obj: Obj, name: str, args: list[Any]) -> tuple[Any, list[Any]]:
        for native in obj.natives:
            method = NATIVE_METHODS.get((native, name))
            if method:
                return method(self, obj, args)
        if name in ('Activate', 'Deactivate'):
            return True, [None] * len(args)
        raise Unsupported('the C++ function %s of %s' % (name, obj.path))

    # ---- expressions

    def eval(self, node: list[Any], frame: Frame, obj: Any = None) -> Any:
        op = node[0]
        target = frame.obj if obj is None else obj
        if op == 'local':
            return frame.vars.get(node[1], 0)
        if op == 'self':
            if isinstance(target, (Obj, Native)):
                return target.props.get(node[1], 0)
            raise Unsupported('a variable of %r' % (target,))
        if op == 'default':
            if isinstance(target, Cls):
                return self.defaults(target.path).get(node[1], 0)
            if isinstance(target, Obj):
                return self.defaults(target.path).get(node[1], 0)
            raise Unsupported('a default of %r' % (target,))
        if op == 'let':
            value = self.eval(node[2], frame)
            self.assign(node[1], value, frame)
            return value
        if op == 'ctx':
            inner = self.eval(node[1], frame)
            if isinstance(inner, str) and inner in self.classes:  # a class in a variable
                inner = Cls(inner)
            if inner is None or inner == 0:
                return 0
            if node[2][0] in ('call', 'vcall'):
                return self.call(node[2], frame, inner)
            return self.eval(node[2], frame, inner)
        if op in ('call', 'vcall'):
            return self.call(node, frame, obj)
        if op == 'member':
            container = self.eval(node[2], frame, obj)
            return container.get(node[1], 0) if isinstance(container, dict) else 0
        if op == 'const':
            value = node[1]
            return f32(value) if isinstance(value, float) else value
        if op == 'obj':
            name = node[1] or ''
            short = name.removeprefix('Default__')
            if short in LIBRARIES or short.endswith(('Library', 'Lib')) or short.startswith('LIB_'):
                return Library(short)
            if short in self.by_name:
                return Cls(self.by_name[short])
            raise Unsupported('the object %s' % name)
        if op == 'selfobj':
            return frame.obj
        if op == 'none':
            return None
        if op == 'cast':
            value = self.eval(node[2], frame)
            cls = node[1] or ''
            if isinstance(value, Obj):
                return value if cls in value.names() else None
            if isinstance(value, Cls):
                return value
            return None
        if op == 'pcast':
            value = self.eval(node[2], frame)
            if node[1] in (0x47, 0x49):  # an object or an interface to a bool
                return value is not None and value != 0
            return value
        if op == 'switch':
            index = _enum(self.eval(node[1], frame))
            for value, result in node[2]:
                if _enum(self.eval(value, frame)) == index:
                    return self.eval(result, frame)
            return self.eval(node[3], frame)
        if op == 'array':
            return [self.eval(n, frame) for n in node[1]]
        if op == 'setarray':
            value = [self.eval(n, frame) for n in node[2]]
            self.assign(node[1], value, frame)
            return value
        if op == 'struct':
            return [self.eval(n, frame) for n in node[2]]
        if op == 'index':
            array = self.eval(node[1], frame)
            index = int(_number(self.eval(node[2], frame)))
            return array[index] if isinstance(array, list) and 0 <= index < len(array) else 0
        if op == 'nothing':
            return None
        raise Unsupported('the node %s' % op)

    def container(self, node: list[Any], frame: Frame, obj: Any = None) -> tuple[dict[str, Any], str]:
        """The dict and key that an assignable node refers to."""
        op = node[0]
        target = frame.obj if obj is None else obj
        if op == 'local':
            return frame.vars, node[1]
        if op == 'self' and isinstance(target, Obj):
            return target.props, node[1]
        if op == 'member':
            outer, key = self.container(node[2], frame, obj)
            inner = outer.get(key)
            if not isinstance(inner, dict):
                inner = outer[key] = {}
            return inner, node[1]
        if op == 'ctx':
            inner = self.eval(node[1], frame)
            if not isinstance(inner, Obj):
                raise Unsupported('an assignment to %r' % (inner,))
            return self.container(node[2], frame, inner)
        raise Unsupported('an assignment to %s' % op)

    def assign(self, node: list[Any], value: Any, frame: Frame) -> None:
        holder, key = self.container(node, frame)
        holder[key] = value


def _merge(into: dict[str, Any], values: dict[str, Any]) -> None:
    """Merges the values of a blueprint into those of its parent. A struct of a blueprint
    holds only the members that are different from the parent's."""
    for key, value in values.items():
        if isinstance(value, dict) and isinstance(into.get(key), dict):
            _merge(into[key], value)
        else:
            into[key] = value


# ---- the C++ code


def _attribute_value(attribute: dict[str, Any]) -> float:
    """FAttribute::RefreshValue: the base value, plus base x value of each Multiply
    modifier, plus each Add modifier. A Set modifier replaces the result."""
    base = f32(_number(attribute.get('BaseValue', 0.0)))
    value = base
    modifiers = attribute.get('Modifiers') or []
    for m in modifiers:
        if _enum(m.get('AttributeMod', 0)) == 1:
            value = f32(value + f32(_number(m.get('Value', 0.0)) * base))
    for m in modifiers:
        if _enum(m.get('AttributeMod', 0)) == 0:
            value = f32(value + _number(m.get('Value', 0.0)))
    for m in modifiers:
        if _enum(m.get('AttributeMod', 0)) == 2:
            value = f32(_number(m.get('Value', 0.0)))
    return value


def _weapon_value(vm: VM, obj: Obj, args: list[Any]) -> tuple[Any, list[Any]]:
    """AWeaponBase::GetEquipmentAttributeValue_Implementation."""
    attribute = int(_number(args[0]))
    c = obj.props.get('WeaponConfig', {})

    def g(key: str) -> float:
        return f32(_number(c.get(key, 0.0)))

    projectiles = int(_number(c.get('AdditionalProjectiles', 0))) + int(
        _number(c.get('AdditionalProjectilesMaxCharge', 0))
    )
    multiplier = f32((projectiles + 1) * f32(g('FullChargeDamagePercentAdd') + 1.0))
    between = g('TimeBetweenShots')
    interval = 1.0
    if between != 0.0:
        burst = max(
            float(int(_number(c.get('ShotsPerBurst', 0))) + int(_number(c.get('AdditionalBurstShotsMaxCharge', 0)))),
            1.0,
        )
        interval = f32(f32(f32(f32((burst - 1.0) * g('BurstDelay')) + g('ChargeTime')) + between) / burst)
    name = ATTRIBUTES[attribute][0] if 0 <= attribute < len(ATTRIBUTES) else ''
    value = 0.0
    if name == 'EnergyConsumptionPerSecond':
        value = g('EnergyConsumption') if g('ChargeTime') > 0.0 else f32(g('EnergyConsumption') / interval)
    elif name == 'FireRate':
        value = f32(1.0 / between) if between != 0.0 else between
    elif name == 'FullChargeAddtionalProjectiles':
        value = float(int(_number(c.get('AdditionalProjectilesMaxCharge', 0))))
    elif name == 'FullChargeDamageMultiplier':
        value = f32(g('FullChargeDamagePercentAdd') + 1.0) if g('FullChargeDamagePercentAdd') > 0.0 else 0.0
    elif name in ('HullDamage', 'HullDamagePerSecond', 'ShieldDamage', 'ShieldDamagePerSecond'):
        kind = 'Hull' if name.startswith('Hull') else 'Shield'
        value = f32(f32(g(kind + 'Damage') * multiplier) + f32(multiplier * g(kind + 'DamageRadial')))
        if name.endswith('PerSecond'):
            value = f32(value / interval)
    elif name == 'ShieldPiercing':
        value = f32(g('ShieldPiercingRatio') * 100.0)
    elif name == 'Range':
        value = f32(g('Range') / 100.0)
    elif name == 'Speed':
        value = f32(g('Speed') / 100.0)
    elif name == 'SpreadDegrees':
        value = g('SpreadDegrees')
    elif name == 'AreaDamageRange':
        value = f32(g('RadialDamageRadius') / 100.0)
    elif name == 'ChargeDuration':
        value = g('ChargeTime')
    elif name == 'CrititcalHitChance':
        # the weapon component of the player's ship, which a class default object has not
        own = obj.props.get('CriticalHitChanceAddAmount') or {}
        base = f32(vm.crit_chance) if obj.player else 0.0
        value = f32(f32(base + _attribute_value(own)) * 100.0)
    return value != 0.0, [None, value]


def _projectile_value(vm: VM, obj: Obj, args: list[Any]) -> tuple[Any, list[Any]]:
    """AWeaponProjectile::GetEquipmentAttributeValue_Implementation: Homing, else the weapon's."""
    if int(_number(args[0])) == HOMING:
        value = 1.0 if obj.props.get('bIsHoming') else 0.0
        return True, [None, value]
    return _weapon_value(vm, obj, args)


def _device_value(vm: VM, obj: Obj, args: list[Any], shield: bool = False) -> tuple[Any, list[Any]]:
    """ADeviceBase and AShieldBase::GetEquipmentAttributeValue_Implementation."""
    name = ATTRIBUTES[int(_number(args[0]))][0]
    p = obj.props
    passive = _enum(p.get('DeviceType', 0)) == 1
    fields = {
        'CoolDownDuration': 'CoolDownDuration',
        'EffectDuration': 'EffectDuration',
    }
    if shield:
        fields.update(
            {
                'ShieldHitpoints': 'MaxHitpoints',
                'ShieldRechargeDelayAfterHit': 'RechargeDelayAfterHit',
                'ShieldRechargePerSecond': 'RechargePerSecond',
                'ShieldShutdownDuration': 'ShutDownDuration',
            }
        )
    if name in fields:
        return True, [None, f32(_number(p.get(fields[name], 0.0)))]
    if name == 'EnergyAllocation' and passive or name == 'EnergyConsumption' and not passive:
        return True, [None, f32(_number(p.get('EnergyConsumption', 0.0)))]
    return False, [None, 0.0]


def _no_value(vm: VM, obj: Obj, args: list[Any]) -> tuple[Any, list[Any]]:
    return False, [None, 0.0]


def _no_install(vm: VM, obj: Obj, args: list[Any]) -> tuple[Any, list[Any]]:
    return False, [None] * len(args)


NATIVE_METHODS = {
    ('WeaponBase', 'GetEquipmentAttributeValue'): _weapon_value,
    ('WeaponProjectile', 'GetEquipmentAttributeValue'): _projectile_value,
    ('DeviceBase', 'GetEquipmentAttributeValue'): _device_value,
    ('ShieldBase', 'GetEquipmentAttributeValue'): lambda vm, obj, args: _device_value(vm, obj, args, shield=True),
    ('EquipmentBase', 'GetEquipmentAttributeValue'): _no_value,
    ('ModBase', 'OnInstall'): _no_install,
}


# ---- the library functions that the game's blueprints call


def _values(vm: VM, frame: Frame, nodes: list[Any]) -> list[Any]:
    return [vm.eval(n, frame) for n in nodes]


def _math(function: Any) -> Any:
    def call(vm: VM, frame: Frame, nodes: list[Any]) -> Any:
        return function(*_values(vm, frame, nodes))

    return call


def _f(function: Any) -> Any:
    return _math(lambda *a: f32(function(*[_number(x) for x in a])))


def _b(function: Any) -> Any:
    return _math(lambda *a: bool(function(*[_number(x) for x in a])))


def _divide(a: float, b: float) -> float:
    return 0.0 if b == 0 else a / b


def _random_fraction(stream: dict[str, Any]) -> float:
    """FRandomStream::GetFraction, which also moves the stream on."""
    seed = (int(stream.get('Seed', 0)) * 196314165 + 907633515) & 0xFFFFFFFF
    stream['Seed'] = seed
    return f32(struct.unpack('<f', struct.pack('<I', 0x3F800000 | (seed >> 9)))[0] - 1.0)


def _stream(vm: VM, frame: Frame, node: list[Any]) -> dict[str, Any]:
    holder, key = vm.container(node, frame)
    stream = holder.get(key)
    if not isinstance(stream, dict):
        stream = holder[key] = {'InitialSeed': 0, 'Seed': 0}
    return stream


def _set_seed(vm: VM, frame: Frame, nodes: list[Any]) -> None:
    stream = _stream(vm, frame, nodes[0])
    seed = int(_number(vm.eval(nodes[1], frame)))
    stream['InitialSeed'] = seed
    stream['Seed'] = seed & 0xFFFFFFFF


def _reset_stream(vm: VM, frame: Frame, nodes: list[Any]) -> None:
    stream = _stream(vm, frame, nodes[0])
    stream['Seed'] = int(stream.get('InitialSeed', 0)) & 0xFFFFFFFF


def _random_float(vm: VM, frame: Frame, nodes: list[Any]) -> float:
    return _random_fraction(_stream(vm, frame, nodes[0]))


def _random_float_range(vm: VM, frame: Frame, nodes: list[Any]) -> float:
    low, high = (f32(_number(vm.eval(n, frame))) for n in nodes[:2])
    return f32(low + f32(f32(high - low) * _random_fraction(_stream(vm, frame, nodes[2]))))


def _random_int_range(vm: VM, frame: Frame, nodes: list[Any]) -> int:
    low, high = (int(_number(vm.eval(n, frame))) for n in nodes[:2])
    count = high - low + 1
    fraction = _random_fraction(_stream(vm, frame, nodes[2]))
    return low + (int(f32(fraction * count)) if count > 0 else 0)


def _array(vm: VM, frame: Frame, node: list[Any]) -> list[Any]:
    holder, key = vm.container(node, frame)
    array = holder.get(key)
    if not isinstance(array, list):
        array = holder[key] = []
    return array


def _array_get(vm: VM, frame: Frame, nodes: list[Any]) -> None:
    array = vm.eval(nodes[0], frame)
    index = int(_number(vm.eval(nodes[1], frame)))
    item = array[index] if isinstance(array, list) and 0 <= index < len(array) else 0
    vm.assign(nodes[2], copy.deepcopy(item), frame)


def _array_set(vm: VM, frame: Frame, nodes: list[Any]) -> None:
    array = _array(vm, frame, nodes[0])
    index = int(_number(vm.eval(nodes[1], frame)))
    item = vm.eval(nodes[2], frame)
    grow = bool(vm.eval(nodes[3], frame)) if len(nodes) > 3 else False
    if index >= len(array) and grow:
        array.extend([0] * (index + 1 - len(array)))
    if 0 <= index < len(array):
        array[index] = item


def _array_add(vm: VM, frame: Frame, nodes: list[Any]) -> int:
    array = _array(vm, frame, nodes[0])
    array.append(vm.eval(nodes[1], frame))
    return len(array) - 1


def _array_length(vm: VM, frame: Frame, nodes: list[Any]) -> int:
    array = vm.eval(nodes[0], frame)
    return len(array) if isinstance(array, list) else 0


def _object_class(vm: VM, frame: Frame, nodes: list[Any]) -> Any:
    value = vm.eval(nodes[0], frame)
    return Cls(value.path) if isinstance(value, Obj) else None


def _default_object(vm: VM, frame: Frame, nodes: list[Any]) -> Any:
    value = vm.eval(nodes[0], frame)
    return vm.instance(value.path) if isinstance(value, Cls) else None


def _add_modifier(vm: VM, frame: Frame, nodes: list[Any]) -> dict[str, Any]:
    attribute = copy.deepcopy(vm.eval(nodes[0], frame)) or _attribute_struct()
    modifier = vm.eval(nodes[1], frame)
    if isinstance(modifier, list):  # a struct made in the code: AttributeMod, Value
        modifier = {'AttributeMod': modifier[0], 'Value': modifier[1]}
    attribute.setdefault('Modifiers', []).append(dict(modifier) if isinstance(modifier, dict) else {})
    attribute['isDirty'] = True
    return attribute


def _is_valid(vm: VM, frame: Frame, nodes: list[Any]) -> bool:
    value = vm.eval(nodes[0], frame)
    return isinstance(value, (Obj, Cls, Native))


def _nothing(vm: VM, frame: Frame, nodes: list[Any]) -> None:
    for n in nodes:
        vm.eval(n, frame)


LIBRARIES = {
    'KismetMathLibrary',
    'KismetArrayLibrary',
    'KismetSystemLibrary',
    'KismetStringLibrary',
    'KismetTextLibrary',
    'GameplayStatics',
    'GameplayLib',
    'UtilityLib',
}

LIBRARY_FUNCTIONS: dict[str, Any] = {
    'Add_FloatFloat': _f(lambda a, b: a + b),
    'Subtract_FloatFloat': _f(lambda a, b: a - b),
    'Multiply_FloatFloat': _f(lambda a, b: a * b),
    'Divide_FloatFloat': _f(_divide),
    'Multiply_IntFloat': _f(lambda a, b: a * b),
    'Divide_IntFloat': _f(_divide),
    'FMax': _f(max),
    'FMin': _f(min),
    'FClamp': _f(lambda v, lo, hi: min(max(v, lo), hi)),
    'Abs': _f(abs),
    'Lerp': _f(lambda a, b, alpha: a + alpha * (b - a)),
    'Percent_FloatFloat': _f(lambda a, b: math.fmod(a, b) if b else 0.0),
    'Conv_IntToFloat': _f(lambda a: a),
    'Conv_ByteToFloat': _f(lambda a: a),
    'Conv_BoolToFloat': _f(lambda a: a),
    'Add_IntInt': _math(lambda a, b: int(_number(a)) + int(_number(b))),
    'Subtract_IntInt': _math(lambda a, b: int(_number(a)) - int(_number(b))),
    'Multiply_IntInt': _math(lambda a, b: int(_number(a)) * int(_number(b))),
    'Divide_IntInt': _math(lambda a, b: int(int(_number(a)) / int(_number(b))) if int(_number(b)) else 0),
    'Conv_ByteToInt': _math(lambda a: int(_number(a))),
    'Conv_IntToByte': _math(lambda a: int(_number(a)) & 0xFF),
    'Conv_BoolToInt': _math(lambda a: int(bool(a))),
    'FTrunc': _math(lambda a: int(_number(a))),
    'Round': _math(lambda a: math.floor(_number(a) + 0.5)),
    'FFloor': _math(lambda a: math.floor(_number(a))),
    'FCeil': _math(lambda a: math.ceil(_number(a))),
    'Max': _math(lambda a, b: max(int(_number(a)), int(_number(b)))),
    'Min': _math(lambda a, b: min(int(_number(a)), int(_number(b)))),
    'Clamp': _math(lambda v, lo, hi: min(max(int(_number(v)), int(_number(lo))), int(_number(hi)))),
    'Greater_FloatFloat': _b(lambda a, b: a > b),
    'GreaterEqual_FloatFloat': _b(lambda a, b: a >= b),
    'Less_FloatFloat': _b(lambda a, b: a < b),
    'LessEqual_FloatFloat': _b(lambda a, b: a <= b),
    'EqualEqual_FloatFloat': _b(lambda a, b: a == b),
    'NotEqual_FloatFloat': _b(lambda a, b: a != b),
    'Greater_IntInt': _b(lambda a, b: a > b),
    'GreaterEqual_IntInt': _b(lambda a, b: a >= b),
    'Less_IntInt': _b(lambda a, b: a < b),
    'LessEqual_IntInt': _b(lambda a, b: a <= b),
    'EqualEqual_IntInt': _b(lambda a, b: a == b),
    'NotEqual_IntInt': _b(lambda a, b: a != b),
    'EqualEqual_ByteByte': _b(lambda a, b: a == b),
    'NotEqual_ByteByte': _b(lambda a, b: a != b),
    'EqualEqual_BoolBool': _b(lambda a, b: bool(a) == bool(b)),
    'NotEqual_BoolBool': _b(lambda a, b: bool(a) != bool(b)),
    'BooleanAND': _b(lambda a, b: a and b),
    'BooleanOR': _b(lambda a, b: a or b),
    'BooleanXOR': _b(lambda a, b: bool(a) != bool(b)),
    'Not_PreBool': _b(lambda a: not a),
    'SelectFloat': _math(lambda a, b, pick: f32(_number(a if pick else b))),
    'SelectInt': _math(lambda a, b, pick: a if pick else b),
    'SelectObject': _math(lambda a, b, pick: a if pick else b),
    'EqualEqual_ObjectObject': _math(lambda a, b: a is b),
    'NotEqual_ObjectObject': _math(lambda a, b: a is not b),
    'EqualEqual_ClassClass': _math(lambda a, b: getattr(a, 'path', a) == getattr(b, 'path', b)),
    'SetRandomStreamSeed': _set_seed,
    'ResetRandomStream': _reset_stream,
    'RandomFloatFromStream': _random_float,
    'RandomFloatInRangeFromStream': _random_float_range,
    'RandomIntegerInRangeFromStream': _random_int_range,
    'Array_Get': _array_get,
    'Array_Set': _array_set,
    'Array_Length': _array_length,
    'Array_LastIndex': lambda vm, frame, nodes: _array_length(vm, frame, nodes) - 1,
    'Array_IsValidIndex': lambda vm, frame, nodes: (
        0 <= int(_number(vm.eval(nodes[1], frame))) < _array_length(vm, frame, nodes[:1])
    ),
    'Array_Contains': lambda vm, frame, nodes: vm.eval(nodes[1], frame) in (vm.eval(nodes[0], frame) or []),
    'GetObjectClass': _object_class,
    'GetDefaultObject': _default_object,
    'GetPlayerPawn': lambda vm, frame, nodes: None,
    'GetPlayerController': lambda vm, frame, nodes: None,
    'IsValid': _is_valid,
    'IsValidClass': _is_valid,
    'CreateAttributeAddModifier': _add_modifier,
    'MakeLiteralFloat': _f(lambda a: a),
    'MakeLiteralInt': _math(lambda a: int(_number(a))),
    'MakeLiteralBool': _math(bool),
    'MeterToUnrealUnits': _f(lambda a: a * 100.0),
    'UnrealUnitsToMeter': _f(lambda a: a / 100.0),
    'Array_Add': _array_add,
    'GetGameInstanceBaseWithoutContext': lambda vm, frame, nodes: vm.game_instance,
    'GetGameInstanceBase': lambda vm, frame, nodes: vm.game_instance,
    'PrintString': _nothing,
    'PrintText': _nothing,
}


# ---- the rows of the equipment screen


def _format_number(value: float, whole: bool) -> str:
    """FText::AsNumber as the equipment screen calls it. It rounds half to even to 2
    decimals (none for `whole`). It puts a comma between the groups of thousands, and it
    removes trailing zeros."""
    digits = 0 if whole else 2
    rounded = Decimal(value).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_EVEN)
    sign = '-' if rounded < 0 else ''
    text = format(abs(rounded), 'f')
    whole_part, _, fraction = text.partition('.')
    fraction = fraction.rstrip('0')
    grouped = '{:,}'.format(int(whole_part))
    return sign + grouped + ('.' + fraction if fraction else '')


def attribute_name(index: int) -> str:
    return ATTRIBUTES[index][1].upper()


def attribute_text(index: int, value: float) -> str:
    return ATTRIBUTES[index][2].replace('{0}', _format_number(value, index in WHOLE))


def values(vm: VM, obj: Obj, attributes: list[str]) -> dict[int, float]:
    """The values that GetEquipmentAttributeValue returns true for, by attribute."""
    out = {}
    for name in attributes:
        index = ATTRIBUTE_INDEX.get(name)
        if index is None:
            continue
        try:
            shown, after = vm.call_method(obj, 'GetEquipmentAttributeValue', [index, 0.0])
        except Unsupported, RecursionError:
            continue
        if shown:
            out[index] = f32(_number(after[1]))
    return out


def _install(vm: VM, item: Obj, mods: list[str], seeds: list[int]) -> list[str]:
    """Runs OnInstall of each mod on the item. Returns the mods whose code cannot run."""
    failed = []
    for i, path in enumerate(mods):
        try:
            mod = vm.instance(path)
            mod.props['Seed'] = seeds[i] if i < len(seeds) else 0
            vm.call_method(mod, 'OnInstall', [item])
        except Unsupported, RecursionError:
            failed.append(path)
    return failed


def compare(index: int, value: float, baseline: dict[int, float]) -> str:
    """AEquipmentBase::CompareAttributes against the class default object."""
    if index == HOMING or index not in baseline:
        return ''
    other = baseline[index]
    if value == other:
        return ''
    lower = ATTRIBUTES[index][3]
    return 'better' if (value < other) == lower else 'worse'


def rows(
    game: GameData,
    path: str,
    mods: list[str] | None = None,
    seeds: list[int] | None = None,
    perks: dict[str, float] | None = None,
    ship: int | None = None,
) -> tuple[list[Row], list[str]]:
    """The attribute rows of an item, as the equipment screen shows them. perks: the values
    of the pilot's perks by ID, for the critical hit chance and the nanobot repair. ship: the
    ship of the run, for the class restriction. Also returns the mods whose effect cannot be
    calculated."""
    entry = game.equipment.get(path, {})
    out: list[Row] = []
    incompatible = entry.get('incompatible_ships') or []
    if incompatible:
        names = game.texts.get('GetShipClassName', {})
        allowed = [i for i, c in enumerate(SHIP_CLASSES) if c not in incompatible]
        text = '\n'.join(
            names.get('GET_SHIP_CLASS_NAME_' + SHIP_CLASS_KEYS[i], SHIP_CLASSES[i].upper()) for i in allowed
        )
        state = '' if ship is None else 'better' if ship in allowed else 'worse'
        label = game.texts.get('EquipmentInfo', {}).get('EQUIPMENT_INFO_CLASS_RESTRICTION', 'CLASS RESTRICTION')
        out.append(Row('', label, text, None, state))
    attributes = entry.get('attributes') or []
    if not attributes or path not in game.classes:
        return out, []
    vm = VM(game, perks)
    try:
        item = vm.instance(path)
    except Unsupported:
        return out, []
    item.player = True
    failed = _install(vm, item, list(mods or []), list(seeds or []))
    own = values(vm, item, attributes)
    baseline = values(vm, vm.instance(path), attributes)
    for name in attributes:
        index = ATTRIBUTE_INDEX.get(name)
        if index is None or index not in own:
            continue
        value = own[index]
        if index == HOMING and value <= 0:
            continue  # GetEquipmentAttributeDisplayInfo shows Homing only when it is above 0
        text = attribute_text(index, value)
        out.append(Row(name, attribute_name(index), text, value, compare(index, value, baseline)))
    return out, failed


def mod_rows(game: GameData, path: str, seed: int = 0) -> list[Row]:
    """The rows of a mod's own attributes, as the game shows them on the mod."""
    attributes = game.equipment.get(path, {}).get('attributes') or []
    if not attributes or path not in game.classes:
        return []
    vm = VM(game)
    try:
        mod = vm.instance(path)
    except Unsupported:
        return []
    mod.props['Seed'] = seed
    found = values(vm, mod, attributes)
    return [
        Row(ATTRIBUTES[i][0], attribute_name(i), attribute_text(i, v), v, '')
        for i, v in ((ATTRIBUTE_INDEX[n], found.get(ATTRIBUTE_INDEX[n])) for n in attributes if n in ATTRIBUTE_INDEX)
        if v is not None
    ]

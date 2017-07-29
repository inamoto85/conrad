from conrad.compat import *

import abc
import numpy as np
import operator as op
import cvxpy

from conrad.defs import vec
from conrad.abstract.vector import VectorConstraintQueue
from conrad.physics.units import Gy, DeliveredDose
from conrad.physics.string import dose_from_string
from conrad.optimization.solvers.environment import OPTKIT_INSTALLED
from conrad.optimization.objectives.default_weights import *

if OPTKIT_INSTALLED:
	import optkit as ok
	from optkit.libs.enums import OKFunctionEnums
	fn_enums = OKFunctionEnums()
	def box01_pogs(size, lower_limit, upper_limit):
		if not OPTKIT_INSTALLED:
			raise RuntimeError('module `optkit` not installed')

		expr = ok.api.PogsObjective(size, h='IndBox01')

		U_minus_L = upper_limit - lower_limit

		for i in xrange(size):
			if U_minus_L[i] > 0:
				expr.a[i] = 1. / U_minus_L[i]
				expr.b[i] = lower_limit[i] / U_minus_L[i]
			else:
				expr.a[i] = 1.
				expr.b[i] = 0.
				expr.h[i] = fn_enums.dict['IndEq0']
		return expr

else:
	ok = NotImplemented
	fn_enums = NotImplemented
	box01_pogs = NotImplemented

@add_metaclass(abc.ABCMeta)
class TreatmentObjective(object):
	def __init__(self, **dose_and_weight_params):
		self.normalization = 1.
		self.global_scaling = 1.
		self.__weights = {}
		self.__doses = {}
		self.__aliases = {}
		self.dual_constraint_queue = VectorConstraintQueue()

		alias_dict = dose_and_weight_params.pop('aliases', {})
		for k, v in dose_and_weight_params.items():
			self.__setattr__(str(k), v)
		for attr, aliases in alias_dict.items():
			self.__add_aliases(attr, *aliases)

	def __getattr__(self, name):
		if not name.startswith('_'):
			raw = name.endswith('_raw')
			name = name.replace('_raw', '')

			if name in self.__aliases:
				name = self.__aliases[name]

			if 'weight' in name:
				if raw:
					normalization = 1.
				else:
					normalization = self.normalization
				if name in self.__weights:
					return normalization * self.__weights[name]
				else:
					raise AttributeError(
							'{} has no attribute {}'.format(type(self), name))
			elif 'dose' in name:
				if name in self.__doses:
					return self.__doses[name]
				else:
					raise AttributeError(
							'{} has no attribute {}'.format(type(self), name))

	def __setattr__(self, name, value):
		if self.__aliases is not None:
			if name in self.__aliases:
				name = self.__aliases[name]

		if 'weight' in name and not name.startswith('_'):
			weight = float(value)
			if weight < 0:
				raise ValueError('objective weight must be nonnegative')
			self.__weights[name] = weight
		elif 'dose' in name and not name.startswith('_'):
			if isinstance(value, str):
				dose = dose_from_string(value)
			else:
				dose = value
			if not isinstance(dose, DeliveredDose):
				raise TypeError(
						'objective dose argument `{}` must be of (or '
						'parsable as) type {}'
						''.format(name, DeliveredDose))
			else:
				self.__doses[name] = dose
		else:
			super(TreatmentObjective, self).__setattr__(name, value)

	def __add_aliases(self, attribute_name, *aliases):
		if attribute_name in self.__weights or attribute_name in self.__doses:
			for a in aliases:
				self.__aliases.update({str(a): attribute_name})

	def change_parameters(self, **parameters):
		for p in parameters:
			val = parameters[p]
			if p in self.__aliases:
				p = self.__aliases[p]
			if p in self.__doses or p in self.__weights:
				self.__setattr__(p, val)

	def scale(self, nonnegative_scalar):
		if float(nonnegative_scalar) >= 0:
			for k in self.__weights:
				self.__weights[k] *= nonnegative_scalar
		else:
			raise ValueError('scaling must be nonnegative')

	def __mul__(self, other):
		return self.__imul__(other)

	def __rmul__(self, other):
		return self.__imul__(other)

	def __imul__(self, other):
		self.scale(other)
		return self

	def __eq__(self, other):
		if not isinstance(other, TreatmentObjective):
			raise TypeError(
					'equality comparison only defined when compared '
					'object also of type {}'.format(TreatmentObjective))
		param_other = other.parameters
		param_self = self.parameters
		eq = other.global_scaling == self.global_scaling
		eq &= other.normalization == self.normalization
		for k in param_self:
			eq &=k in param_other
			if eq:
				eq &= param_other[k] == param_self[k]
		return eq

	def eval(self, y, voxel_weights=None):
		return self.primal_eval(y, voxel_weights)

	def expr(self, y_var, voxel_weights=None):
		return self.primal_expr(y_var, voxel_weights)

	def expr_Ax(self, A, x_var, voxel_weights=None):
		return self.primal_expr_Ax(A, x_var, voxel_weights)

	@abc.abstractproperty
	def objective_type(self):
		raise NotImplementedError

	@abc.abstractproperty
	def is_target_objective(self):
		raise NotImplementedError

	@abc.abstractproperty
	def is_nontarget_objective(self):
		raise NotImplementedError

	@abc.abstractmethod
	def primal_eval(self, y, voxel_weights=None):
		raise NotImplementedError

	@abc.abstractmethod
	def dual_eval(self, y_dual, voxel_weights=None):
		raise NotImplementedError

	def in_dual_domain(self, nu, voxel_weights=None, nu_offset=None,
					   nonnegative=False, reltol=1e-3, abstol=1e-4):
		weight_vec = 1. if voxel_weights is None else vec(voxel_weights)
		offset = 0. if nu_offset is None else vec(nu_offset)
		self.dual_constraint_queue.clear()
		self.build_dual_domain_constraints(weight_vec)
		return self.dual_constraint_queue.satisfies_all(
				nu + offset, reltol=reltol, abstol=abstol)

	@abc.abstractmethod
	def build_dual_domain_constraints(self, voxel_weights):
		raise NotImplementedError

	@abc.abstractmethod
	def primal_expr(self, y_var, voxel_weights=None):
		raise NotImplementedError

	@abc.abstractmethod
	def primal_expr_Ax(self, A, x_var, voxel_weights=None):
		raise NotImplementedError

	@abc.abstractmethod
	def dual_expr(self, y_dual_var, voxel_weights=None):
		raise NotImplementedError

	@abc.abstractmethod
	def dual_domain_constraints(self, nu_var, voxel_weights=None,
								nu_offset=None, nonnegative=False):
		raise NotImplementedError

	@abc.abstractmethod
	def primal_expr_pogs(self, size, voxel_weights=None):
		raise NotImplementedError

	@abc.abstractmethod
	def dual_expr_pogs(self, size, voxel_weights=None):
		raise NotImplementedError

	@abc.abstractmethod
	def dual_domain_constraints_pogs(self, size, voxel_weights=None,
									 nu_offset=None, nonnegative=False):
		raise NotImplementedError

	@abc.abstractmethod
	def dual_fused_expr_constraints_pogs(self, structure, voxel_weights=None,
										 nu_offset=None, nonnegative=False):
		raise NotImplementedError

	@property
	def parameters(self):
		p = {}
		p.update({k: str(self.__doses[k]) for k in self.__doses})
		p.update(self.__weights)
		return p

	@property
	def dict(self):
		return {
				'type': self.objective_type,
				'parameters': self.parameters
		}

	def string(self, offset=0):
		string = ''
		offset = int(offset) * '\t'
		string += offset + 'type: %s\n' %self.objective_type
		string += offset + 'parameters:\n'
		offset += '\t'
		parameters = self.parameters
		for param in parameters:
			string += offset + param + ': ' + str(parameters[param]) + '\n'
		string += offset + 'current normalization: %f\n' %self.normalization
		string += offset + 'current global scaling: %f\n' %self.global_scaling
		return string

	def __str__(self):
		return self.string()

	def __repr__(self):
		return self.string()
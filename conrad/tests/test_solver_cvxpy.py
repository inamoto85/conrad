from numpy import ceil

from conrad.compat import *
from conrad.defs import module_installed
from conrad.medicine import Structure, D
from conrad.physics import Gy
from conrad.optimization.solver_cvxpy import *
from conrad.tests.base import *
from conrad.tests.test_solver import SolverGenericTestCase

class SolverCVXPYTestCase(SolverGenericTestCase):
	""" TODO: docstring"""
	def test_solver_cvxpy_init(self):
		s = SolverCVXPY()
		if s is None:
			return

		self.assertTrue( s.objective is None )
		self.assertTrue( s.constraints is None )
		self.assertTrue( s.problem is None )
		self.assertTrue( isinstance(s._SolverCVXPY__x, Variable) )
		self.assertTrue( isinstance(s._SolverCVXPY__constraint_indices, dict) )
		self.assertTrue( len(s._SolverCVXPY__constraint_indices) == 0 )
		self.assertTrue( isinstance(s.constraint_dual_vars, dict) )
		self.assertTrue( len(s.constraint_dual_vars) == 0 )
		self.assertTrue( s.n_beams == 0 )

	def test_solver_cvxpy_problem_init(self):
		n_beams = self.n
		s = SolverCVXPY()
		if s is None:
			return

		s.init_problem(n_beams)
		self.assertTrue( s.use_slack )
		self.assertFalse( s.use_2pass )
		self.assertTrue( s.n_beams == n_beams )
		self.assertTrue( s.objective is not None )
		self.assertTrue( len(s.constraints) == 1 )
		self.assertTrue( s.problem is not None )

		for slack_flag in (True, False):
			for two_pass_flag in (True, False):
				s.init_problem(n_beams, use_slack=slack_flag,
							   use_2pass=two_pass_flag)
				self.assertTrue( s.use_slack == slack_flag )
				self.assertTrue( s.use_2pass == two_pass_flag )

		s.init_problem(n_beams, gamma=1.2e-3)
		self.assert_scalar_equal( s.gamma, 1.2e-3 )

	def assert_problems_equivalent(self, p1, p2):
		pd1 = p1.get_problem_data('ECOS')
		pd2 = p2.get_problem_data('ECOS')

		self.assertTrue( sum(pd1['c'] - pd2['c']) == 0 )
		self.assertTrue( len((pd1['G'] - pd2['G']).data) == 0 )

		return pd1['c'].shape, pd1['G'].shape

	def test_percentile_constraint_restricted(self):
		n_beams = self.n
		s = SolverCVXPY()
		if s is None:
			return

		beta = Variable(1)
		x = Variable(n_beams)
		A = self.A_targ

		# lower dose limit:
		#
		#	NONCONVEX CONSTRAINT:
		#
		#	D(percentile) >= dose
		#			---> dose received by P% of tissue >= dose
		#			---> at most (100 - P)% of tissue below dose
		#
		#	sum 1_{ y < dose } <= (100 - percentile)% of structure
		#	sum 1_{ y < dose } <= (1 - fraction) * structure size
		#
		#
		#	CONVEX RESTRICTION:
		#	slope * { y < (dose + 1 / slope)}_- <= (1 - fraction) * size
		#			---> let beta = 1 / slope
		#
		#	(1 / beta) * \sum { y - dose + beta }_- <= (1 - fraction) * size
		#	\sum {beta - y + dose}_+ <= beta * (1 - fraction) * size
		#
		constr = D(80) >= 10 * Gy
		dose = constr.dose.value

		objective = Minimize(0)

		theta = (1 - constr.percentile.fraction) * self.m_target
		c = s._SolverCVXPY__percentile_constraint_restricted(
				A, x, constr, beta)
		c_direct = sum_entries(pos(beta + (-1) * (A*x - dose))) <= beta * theta

		obj_shape, mat_shape = self.assert_problems_equivalent(
				Problem(Minimize(0), [c]), Problem(Minimize(0), [c_direct]) )

		# m voxels, n beams, 1 slope variable (beta), 0 slack variables
		var_count = self.m_target + self.n + 1
		constr_count = 2 * self.m_target + 1

		self.assertTrue( obj_shape[0] == mat_shape[1] )
		self.assertTrue( obj_shape[0] == var_count )
		self.assertTrue( mat_shape[0] == constr_count )

		# upper dose limit
		#
		#	NONCONVEX CONSTRAINT:
		#
		#	D(percentile) <= dose
		#			---> dose received by (100-P)% of tissue <= dose
		#			---> at most P% of tissue above dose
		#
		#	sum 1_{ y > dose } <= (percentile)% of structure
		#	sum 1_{ y > dose } <= fraction * structure size
		#
		#
		#	CONVEX RESTRICTION:
		#	slope * { y > (dose - 1 / slope)}_+ <= fraction * size
		#			---> let beta = 1 / slope
		#
		#	(1 / beta) * \sum { y - dose + beta }_+ <= fraction * size
		#	\sum {beta + y - dose}_+ <= beta * fraction * size
		#
		constr = D(80) <= 10 * Gy
		dose = constr.dose.value

		objective = Minimize(0)

		theta = constr.percentile.fraction * self.m_target
		c = s._SolverCVXPY__percentile_constraint_restricted(
				A, x, constr, beta)
		c_direct = sum_entries(pos(beta + (A*x - dose))) <= beta * theta

		obj_shape, mat_shape = self.assert_problems_equivalent(
				Problem(Minimize(0), [c]), Problem(Minimize(0), [c_direct]) )

		# m voxels, n beams, 1 slope variable (beta), 0 slack variables
		var_count = self.m_target + self.n + 1
		constr_count = 2 * self.m_target + 1

		self.assertTrue( obj_shape[0] == mat_shape[1] )
		self.assertTrue( obj_shape[0] == var_count )
		self.assertTrue( mat_shape[0] == constr_count )

		# lower dose limit, with slack allowing dose threshold to be lower
		#
		#	\sum {beta - y + (dose - slack)}_+ <= beta * (1 - fraction) * size
		#
		slack = Variable(1)

		constr = D(80) >= 10 * Gy
		dose = constr.dose.value

		objective = Minimize(0)

		theta = (1 - constr.percentile.fraction) * self.m_target
		c = s._SolverCVXPY__percentile_constraint_restricted(
				A, x, constr, beta, slack=slack)
		c_direct = sum_entries(pos(
				beta + (-1) * (A * x - (dose - slack)))) <= beta * theta

		obj_shape, mat_shape = self.assert_problems_equivalent(
				Problem(Minimize(0), [c]), Problem(Minimize(0), [c_direct]) )

		# m voxels, n beams, 1 slope variable (beta), 1 slack variable
		var_count = self.m_target + self.n + 2
		constr_count = 2 * self.m_target + 1

		self.assertTrue( obj_shape[0] == mat_shape[1] )
		self.assertTrue( obj_shape[0] == var_count )
		self.assertTrue( mat_shape[0] == constr_count )

		# upper dose limit, with slack allowing dose theshold to be higher
		#
		#	\sum {beta + y - (dose + slack)}_+ <= beta * fraction * size
		#
		constr = D(80) <= 10 * Gy
		dose = constr.dose.value

		objective = Minimize(0)

		theta = constr.percentile.fraction * self.m_target
		c = s._SolverCVXPY__percentile_constraint_restricted(
				A, x, constr, beta, slack=slack)
		c_direct = sum_entries(
				pos(beta + (A * x - (dose + slack)))) <= beta * theta

		obj_shape, mat_shape = self.assert_problems_equivalent(
				Problem(Minimize(0), [c]), Problem(Minimize(0), [c_direct]) )

		# m voxels, n beams, 1 slope variable (beta), 1 slack variable
		var_count = self.m_target + self.n + 2
		constr_count = 2 * self.m_target + 1

		self.assertTrue( obj_shape[0] == mat_shape[1] )
		self.assertTrue( obj_shape[0] == var_count )
		self.assertTrue( mat_shape[0] == constr_count )

	def test_percentile_constraint_exact(self):
		n_beams = self.n
		s = SolverCVXPY()
		if s is None:
			return

		beta = Variable(1)
		x = Variable(n_beams)
		A = self.A_targ
		constr_size = (self.m_target, 1)

		# lower dose limit, exact
		#
		#	y[chosen indices] > dose
		#
		constr = D(80) >= 10 * Gy
		dose = constr.dose.value
		y = rand(self.m_target)

		m_exact = int(ceil(self.m_target * constr.percentile.fraction))
		# ensure constraint is met by vector y
		y[:m_exact] += 10
		A_exact = A[constr.get_maxmargin_fulfillers(y), :]

		c = s._SolverCVXPY__percentile_constraint_exact(A, x, y, constr,
														had_slack=False)
		c_direct = A_exact * x >= dose
		obj_shape, mat_shape = self.assert_problems_equivalent(
				Problem(Minimize(0), [c]), Problem(Minimize(0), [c_direct]) )
		self.assertTrue( obj_shape[0] == mat_shape[1] )
		self.assertTrue( obj_shape[0] == self.n )
		self.assertTrue( mat_shape[0] == m_exact )

		# upper dose limit, exact
		#
		#	y[chosen indices] < dose
		#
		constr = D(80) <= 10 * Gy
		dose = constr.dose.value
		y = rand(self.m_target)

		m_exact = int(ceil(self.m_target * (1 - constr.percentile.fraction)))
		# ensure constraint is met by vector y
		y[m_exact:] += 10
		A_exact = A[constr.get_maxmargin_fulfillers(y), :]

		c = s._SolverCVXPY__percentile_constraint_exact(A, x, y, constr,
														had_slack=False)
		c_direct = A_exact * x <= dose
		obj_shape, mat_shape = self.assert_problems_equivalent(
				Problem(Minimize(0), [c]), Problem(Minimize(0), [c_direct]) )
		self.assertTrue( obj_shape[0] == mat_shape[1] )
		self.assertTrue( obj_shape[0] == self.n )
		self.assertTrue( mat_shape[0] == m_exact )

	def test_add_constraints(self):
		s = SolverCVXPY()
		if s is None:
			return

		x = Variable(self.n)
		p = Problem(Minimize(0), [x >= 0])

		s.init_problem(self.n, use_slack=False, use_2pass=False)
		self.assert_problems_equivalent( p, s.problem )

		# no constraints
		s._SolverCVXPY__add_constraints(self.anatomy['tumor'])
		self.assert_problems_equivalent( p, s.problem )

		# add mean constraint
		constr = D('mean') <= 10 * Gy
		constr_cvxpy = self.anatomy['tumor'].A_mean * x <= constr.dose.value
		self.anatomy['tumor'].constraints += constr
		p.constraints = [x>=0, constr_cvxpy]
		s._SolverCVXPY__add_constraints(self.anatomy['tumor'])
		self.assert_problems_equivalent( p, s.problem )

		s.clear()

		# add mean constraint with slack (upper)
		for priority in xrange(1, 4):
			slack = Variable(1)
			s.use_slack = True
			constr = D('mean') <= 10 * Gy
			constr.priority = priority
			dose = constr.dose.value
			constr_cvxpy = self.anatomy['tumor'].A_mean * x - slack <= dose
			self.anatomy['tumor'].constraints.clear()
			self.anatomy['tumor'].constraints += constr
			p.objective += Minimize(s.gamma_prioritized(constr.priority) * slack)
			p.constraints = [x>=0, slack >= 0, constr_cvxpy]
			s._SolverCVXPY__add_constraints(self.anatomy['tumor'])
			self.assert_problems_equivalent( p, s.problem )

			p.objective = Minimize(0)
			s.clear()
			s.use_slack = False

			# add mean constraint with slack (lower)
			slack = Variable(1)
			s.use_slack = True
			constr = D('mean') >= 10 * Gy
			constr.priority = priority
			dose = constr.dose.value
			constr_cvxpy = self.anatomy['tumor'].A_mean * x + slack >= dose
			self.anatomy['tumor'].constraints.clear()
			self.anatomy['tumor'].constraints += constr
			p.objective += Minimize(s.gamma_prioritized(constr.priority) * slack)
			p.constraints = [x>=0, slack >= 0, constr_cvxpy]
			s._SolverCVXPY__add_constraints(self.anatomy['tumor'])
			self.assert_problems_equivalent( p, s.problem )

			p.objective = Minimize(0)
			s.clear()
			s.use_slack = False

		# exact constraint flag=True not allowed when structure.y is None
		self.assertTrue( self.anatomy['tumor'].y is None )
		self.assert_exception( call=s._SolverCVXPY__add_constraints,
							   args=[self.anatomy['tumor']] )
		self.anatomy['tumor'].calculate_dose(rand(self.n))
		self.assertTrue( self.anatomy['tumor'].y is not None )
		self.assert_no_exception( call=s._SolverCVXPY__add_constraints,
								  args=[self.anatomy['tumor']] )
		s.clear()

		# exact constraint flag=True not allowed when use_2pass flag not set
		s.use_2pass = False
		self.assert_exception( call=s._SolverCVXPY__add_constraints,
							   args=[self.anatomy['tumor'], True] )
		s.clear()

		# set slack flag, but set conditions that don't allow for slack
		constr = D('mean') <= 10 * Gy
		self.anatomy['tumor'].constraints.clear()
		self.anatomy['tumor'].constraints += constr
		constr_cvxpy = self.anatomy['tumor'].A_mean * x <= constr.dose.value
		dose = constr.dose.value

		# exact=True cancels out use_slack=True, no slack problem built
		s.use_slack = True
		s.use_2pass = True # (required for exact=True)
		s._SolverCVXPY__add_constraints(self.anatomy['tumor'], exact=True)

		# no slack problem
		p.objective = Minimize(0)
		p.constraints = [x>=0, constr_cvxpy]

		self.assert_problems_equivalent( p, s.problem )
		s.use_slack = False

		# constraint.priority=0 (force no slack) cancels out use_slack=True
		# for *THAT* constraint
		s.clear()
		self.anatomy['tumor'].constraints.clear()
		constr = D('mean') <= 10 * Gy
		constr.priority = 0
		self.anatomy['tumor'].constraints += constr
		# (no slack)
		constr_cvxpy = self.anatomy['tumor'].A_mean * x <= constr.dose.value

		constr2 = D('mean') <= 8 * Gy
		slack = Variable(1)
		self.anatomy['tumor'].constraints += constr2
		# (yes slack)
		constr_cvxpy2 = self.anatomy['tumor'].A_mean * x - slack <= constr2.dose.value

		s.use_slack = True
		s._SolverCVXPY__add_constraints(self.anatomy['tumor'])
		p.objective += Minimize(s.gamma_prioritized(constr2.priority) * slack)

		# try permuting constraints if problem equivalence fails
		try:
			p.constraints = [x>=0, constr_cvxpy, slack>=0, constr_cvxpy2]
			self.assert_problems_equivalent( p, s.problem )
		except:
			p.constraints = [x>=0, slack>=0, constr_cvxpy2, constr_cvxpy]
			self.assert_problems_equivalent( p, s.problem )

		s.use_slack = False

		# add max constraint
		s.clear()
		self.anatomy['tumor'].constraints.clear()
		constr = D('max') <= 30 * Gy
		self.anatomy['tumor'].constraints += constr
		constr_cvxpy = self.anatomy['tumor'].A * x  <= constr.dose.value
		p.objective = Minimize(0)
		p.constraints = [x>=0, constr_cvxpy]
		s._SolverCVXPY__add_constraints(self.anatomy['tumor'])
		self.assert_problems_equivalent( p, s.problem )

		# add min constraint
		s.clear()
		self.anatomy['tumor'].constraints.clear()
		constr = D('min') >= 25 * Gy
		self.anatomy['tumor'].constraints += constr
		constr_cvxpy = self.anatomy['tumor'].A * x  >= constr.dose.value
		p.objective = Minimize(0)
		p.constraints = [x>=0, constr_cvxpy]
		s._SolverCVXPY__add_constraints(self.anatomy['tumor'])
		self.assert_problems_equivalent( p, s.problem )

		# add percentile constraint, restricted.
		# - tested above in test_percentile_constraint_restricted()

		# add percentile constraint, exact
		# - tested above in test_percentile_constraint_exact()

	def test_build(self):
		s = SolverCVXPY()
		if s is None:
			return
		s.init_problem(self.n)

		self.anatomy['tumor'].constraints.clear()
		self.anatomy['oar'].constraints.clear()
		structure_list = self.anatomy.list
		A, dose, weight_abs, weight_lin = s._Solver__gather_matrix_and_coefficients(
				structure_list)

		x = Variable(self.n)
		p = Problem(Minimize(0), [])
		p.constraints += [ x >= 0 ]
		p.objective += Minimize(
				weight_abs.T * abs(A * x) +
				weight_lin.T * (A * x) )

		s.use_slack = False
		s.build(structure_list, exact=False)
		self.assertTrue( len(s.slack_vars) == 0 )
		self.assertTrue( len(s.dvh_vars) == 0 )
		self.assertTrue( len(s._SolverCVXPY__constraint_indices) == 0 )
		self.assert_problems_equivalent( p, s.problem )

		structure_list[0].constraints += D('mean') >= 10 * Gy
		cid = structure_list[0].constraints.last_key

		s.use_slack = False
		s.build(structure_list, exact=False)
		self.assertTrue( len(s.slack_vars) == 1 )
		self.assertTrue( cid in s.slack_vars )
		self.assertTrue( s.get_slack_value(cid) == 0 )
		self.assertTrue( len(s.dvh_vars) == 0 )
		self.assertTrue( len(s._SolverCVXPY__constraint_indices) == 1 )
		self.assertTrue( cid in s._SolverCVXPY__constraint_indices )
		# constraint 0: x >= 0; constraint 1: this
		self.assertTrue( s._SolverCVXPY__constraint_indices[cid] == 1 )
		# dual is none since unsolved, not populated by cvxpy
		self.assertTrue( s.get_dual_value(cid) is None )

		s.use_slack = True
		s.build(structure_list, exact=False)
		self.assertTrue( len(s.slack_vars) == 1 )
		self.assertTrue( cid in s.slack_vars )
		# slack is None since unsolved, not populated by cvxpy
		self.assertTrue( s.get_slack_value(cid) is None )
		# set slack value, as if cvxpy solve called
		s.slack_vars[cid].value = 1
		self.assertTrue( s.get_slack_value(cid) == 1. )
		self.assertTrue( len(s.dvh_vars) == 0 )
		self.assertTrue( len(s._SolverCVXPY__constraint_indices) == 1 )
		self.assertTrue( cid in s._SolverCVXPY__constraint_indices )
		# constraint 0: x >= 0; constraint 1: slack >= 0; cosntraint 2: this
		self.assertTrue( s._SolverCVXPY__constraint_indices[cid] == 2 )

		# add percentile constraint, test slope retrieval
		structure_list[0].constraints += D(20) >= 10 * Gy
		cid2 = structure_list[0].constraints.last_key

		s.use_slack = False
		s.build(structure_list, exact=False)
		self.assertTrue( cid not in s.dvh_vars )
		self.assertTrue( cid2 in s.dvh_vars )
		self.assertTrue( s.dvh_vars[cid2].value is None )
		self.assertTrue( s.get_dvh_slope(cid2) is nan )

		# artificially set value of DVH slope variable
		BETA = 2.
		s.dvh_vars[cid2].value = BETA
		self.assertTrue( s.get_dvh_slope(cid2) == 1. / BETA )


	def test_solve(self):
		s = SolverCVXPY()
		if s is None:
			return
		s.init_problem(self.n, use_slack=False, use_2pass=False)

		# solve variants:

		#	(1) unconstrained
		self.anatomy['tumor'].constraints.clear()
		self.anatomy['oar'].constraints.clear()
		structure_list = self.anatomy.list
		s.build(structure_list, exact=False)

		self.assertTrue( s.x.size == 1 )
		self.assertTrue( s.x_dual.size == 1 )
		self.assertTrue( s.status is None )
		self.assertTrue( s.solveiters == 'n/a' )
		self.assertTrue( s.solvetime is nan )
		self.assertTrue( len(s.slack_vars) == 0 )
		self.assertTrue( len(s.dvh_vars) == 0 )
		self.assertTrue( len(s._SolverCVXPY__constraint_indices) == 0 )

		solver_status = s.solve(verbose=0)
		self.assertTrue( solver_status )
		self.assertTrue( s.x.size == self.n )
		self.assertTrue( s.x_dual.size == self.n )
		self.assertTrue( s.status == 'optimal' )
		self.assertTrue( s.solveiters == 'n/a' )
		self.assertTrue( isinstance(s.solvetime, float) )
		self.assertTrue( len(s.slack_vars) == 0 )
		self.assertTrue( len(s.dvh_vars) == 0 )
		self.assertTrue( len(s._SolverCVXPY__constraint_indices) == 0 )

		#	(2) mean-constrained
		# test constraint dual value retrieval
		structure_list[0].constraints += D('mean') >= 20 * Gy
		cid = structure_list[0].constraints.last_key
		s.build(structure_list, exact=False)
		solver_status = s.solve(verbose=0)
		self.assertTrue( solver_status )
		self.assertTrue( s.get_slack_value(cid) == 0 )

		# constraint is active:
		self.assertTrue( s.get_dual_value(cid) > 0 )

		# redundant constraint
		structure_list[0].constraints += D('mean') >= 10 * Gy
		cid2 = structure_list[0].constraints.last_key
		s.build(structure_list, exact=False)
		solver_status = s.solve(verbose=0)
		self.assertTrue( solver_status )
		self.assertTrue( s.status == 'optimal' )
		self.assertTrue( s.get_slack_value(cid) == 0 )

		# constraint is active:
		self.assertTrue( s.get_dual_value(cid) > 0 )
		# constraint is inactive:
		self.assert_scalar_equal( s.get_dual_value(cid2), 0 )

		# infeasible constraint
		structure_list[0].constraints += D('mean') <= 10 * Gy
		cid3 = structure_list[0].constraints.last_key
		s.build(structure_list, exact=False)
		solver_status = s.solve(verbose=0)
		self.assertFalse( solver_status )
		self.assertTrue( s.status == 'infeasible' )

		# remove infeasible constraint from structure
		structure_list[0].constraints -= cid3

		#	(3) +min constrained
		structure_list[0].constraints += D('min') >= 1 * Gy
		cid_min = structure_list[0].constraints.last_key
		s.build(structure_list, exact=False)
		solver_status = s.solve(verbose=0)
		self.assertTrue( solver_status )
		# assert dual variable is vector
		self.assertTrue( len(s.get_dual_value(cid_min)) ==
						 structure_list[0].A_full.shape[0]  )

		# #	(4) +max constrained
		structure_list[0].constraints += D('max') <= 50 * Gy
		cid_max = structure_list[0].constraints.last_key
		s.build(structure_list, exact=False)
		solver_status = s.solve(verbose=0)
		self.assertTrue( solver_status )
		# assert dual variable is vector
		self.assertTrue( len(s.get_dual_value(cid_max)) ==
						 structure_list[0].A_full.shape[0]  )

		#	(5) +percentile constrained
		structure_list[0].constraints += D(10) >= 0.1 * Gy
		cid_dvh = structure_list[0].constraints.last_key
		s.build(structure_list, exact=False)
		solver_status = s.solve(verbose=0)
		self.assertTrue( solver_status )

		# retrieve percentile constraint slope
		self.assertTrue( isinstance(s.get_dvh_slope(cid_dvh), float) )
		self.assertTrue( s.get_dvh_slope(cid_dvh) > 0 )
		self.assertTrue( isinstance(s.get_dual_value(cid_dvh), float) )

		#	(6) percentile constrained, two-pass
		for structure in structure_list:
			# (calculated doses needed for 2nd pass)
			structure.calculate_dose(s.x)

		s.use_2pass = True # (flag needed to allow for exact below)
		s.build(structure_list, exact=True)
		solver_status = s.solve(verbose=0)
		self.assertTrue( solver_status )
		idx = s._SolverCVXPY__constraint_indices[cid_dvh]

		frac = structure_list[0].constraints[cid_dvh].percentile.fraction
		if structure_list[0].constraints[cid_dvh].upper:
			frac = 1. - frac
		constr_size = int(ceil(structure_list[0].size * frac))
		if constr_size > 1:
			self.assertTrue( len(s.get_dual_value(cid_dvh)) == constr_size )
		else:
			self.assertTrue( isinstance(s.get_dual_value(cid_dvh), float) )
		s.use_2pass = False

		#	(7) with slack
		# infeasible constraint
		structure_list[0].constraints += D('mean') <= 10 * Gy
		cid4 = structure_list[0].constraints.last_key
		s.build(structure_list, exact=False)
		solver_status = s.solve(verbose=0)
		self.assertFalse( solver_status )

		# feasible with slack
		s.use_slack = True
		structure_list[0].constraints[cid].priority = 0
		structure_list[0].constraints[cid4].priority = 1
		s.build(structure_list, exact=False)
		solver_status = s.solve(verbose=0)
		self.assertTrue( solver_status )
		self.assertTrue( s.get_slack_value(cid) == 0 )
		self.assertTrue( s.get_slack_value(cid4) > 0 )

	def test_solver_options(self):
		s = SolverCVXPY()
		if s is None:
			return
		s.init_problem(self.n, use_slack=False, use_2pass=False)

		# solve variants:

		self.anatomy['tumor'].constraints.clear()
		self.anatomy['oar'].constraints.clear()
		structure_list = self.anatomy.list
		structure_list[0].constraints += D('mean') >= 20 * Gy
		structure_list[0].constraints += D(10) >= 0.1 * Gy
		s.build(structure_list, exact=False)

		if module_installed('scs'):
			for INDIRECT in [True, False]:
				for GPU in [True, False]:
					solver_status = s.solve(
							solver=SCS, verbose=0, use_indirect=INDIRECT,
							use_gpu=GPU)
					self.assertTrue( solver_status )

		if module_installed('ecos'):
			solver_status = s.solve(solver=ECOS, verbose=0, use_indirect=INDIRECT)
			self.assertTrue( solver_status )
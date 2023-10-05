# dingo : a python library for metabolic networks sampling and analysis
# dingo is part of GeomScale project

# Copyright (c) 2021 Apostolos Chalkis

# Licensed under GNU LGPL.3, see LICENCE file

import sys
import numpy as np
import scipy.sparse as sp
import gurobipy as gp
from gurobipy import GRB
import math



    

    






def update_model(model, n, Aeq_sparse, beq, lb, ub, A_sparse, b, objective_function):
    """A function to update a gurobi model that solves a linear program
    Keyword arguments:
    model -- gurobi model
    n -- the dimension
    Aeq_sparse -- a sparse matrix s.t. Aeq_sparse x = beq
    beq -- a vector s.t. Aeq_sparse x = beq
    lb -- lower bounds for the variables, i.e., a n-dimensional vector
    ub -- upper bounds for the variables, i.e., a n-dimensional vector
    A_sparse -- a sparse matrix s.t. A_sparse x <= b
    b -- a vector matrix s.t. A_sparse x <= b
    objective_function -- the objective function, i.e., a n-dimensional vector
    """
    model.remove(model.getVars())
    model.update()
    model.remove(model.getConstrs())
    model.update()
    x = model.addMVar(
        shape=n,
        vtype=GRB.CONTINUOUS,
        name="x",
        lb=lb,
        ub=ub,
    )
    model.update()
    model.addMConstr(Aeq_sparse, x, "=", beq, name="c")
    model.update()
    model.addMConstr(A_sparse, x, "<", b, name="d")
    model.update()
    model.setMObjective(None, objective_function, 0.0, None, None, x, GRB.MINIMIZE)
    model.update()

    return model



def solve_lp_with_different_objectives(model, new_objective_coeffs):
    """
    Solve a linear program with a different objective function.

    Parameters:
        model (gurobipy.Model): The Gurobi model with the original constraints.
        new_objective_coeffs (list): List of new objective coefficients for the variables.

    Returns:
        gurobipy.Model: The updated Gurobi model with the new objective function.
    """
    # Clear the existing objective function
    model.setObjective(0, clear=True)

    # Update the objective function with the new coefficients
    for i, var in enumerate(model.getVars()):
        var.setAttr(GRB.Attr.Obj, new_objective_coeffs[i])

    # Optimize the updated model
    model.optimize()

    return model

def fast_remove_redundant_facets(lb, ub, S, c, opt_percentage=100):
    if lb.size != S.shape[1] or ub.size != S.shape[1]:
        raise Exception(
            "The number of reactions must be equal to the number of given flux bounds."
        )

    redundant_facet_tol = 1e-07
    tol = 1e-06

    m = S.shape[0]
    n = S.shape[1]
    beq = np.zeros(m)
    Aeq_res = S

    A = np.zeros((2 * n, n), dtype="float")
    A[0:n] = np.eye(n)
    A[n:] -= np.eye(n, n, dtype="float")

    b = np.concatenate((ub, -lb), axis=0)
    b = np.asarray(b, dtype="float")
    b = np.ascontiguousarray(b, dtype="float")

    max_biomass_flux_vector, max_biomass_objective = fast_fba(lb, ub, S, c)
    val = -np.floor(max_biomass_objective / tol) * tol * opt_percentage / 100

    b_res = []
    A_res = np.empty((0, n), float)
    beq_res = np.array(beq)

    try:
        with gp.Env(empty=True) as env:
            env.setParam("OutputFlag", 0)
            env.start()

            with gp.Model(env=env) as model:
                x = model.addMVar(
                    shape=n,
                    vtype=GRB.CONTINUOUS,
                    name="x",
                    lb=lb,
                    ub=ub,
                )

                Aeq_sparse = sp.csr_matrix(S)
                A_sparse = sp.csr_matrix(np.array(-c))
                b_sparse = np.array(val)

                b = np.array(b)
                beq = np.array(beq)

                model.addMConstr(Aeq_sparse, x, "=", beq, name="c")
                model.update()
                model.addMConstr(A_sparse, x, "<", [val], name="d")
                model.update()

                model_iter = model.copy()

                indices_iter = range(n)
                removed = 1
                offset = 1
                facet_left_removed = np.zeros((1, n), dtype=bool)
                facet_right_removed = np.zeros((1, n), dtype=bool)

                while removed > 0 or offset > 0:
                    removed = 0
                    offset = 0
                    indices = indices_iter
                    indices_iter = []

                    Aeq_sparse = sp.csr_matrix(Aeq_res)
                    beq = np.array(beq_res)

                    b_res = []
                    A_res = np.empty((0, n), float)
                    for i in indices:
                        objective_function = A[i]

                        redundant_facet_right = True
                        redundant_facet_left = True

                        objective_function_max = np.asarray(
                            [-x for x in objective_function]
                        )

                        model_iter = solve_lp_with_different_objectives(
                            model_iter.copy(), objective_function_max
                        )


                        status = model_iter.status
                        if status == GRB.OPTIMAL:
                            max_objective = -model_iter.objVal
                        else:
                            max_objective = ub[i]

                        if not facet_right_removed[0, i]:
                            ub_iter = ub.copy()
                            ub_iter[i] = ub_iter[i] + 1

                            # Call solve_lp_with_different_objectives to solve LP
                            model_iter = solve_lp_with_different_objectives(
                                model_iter.copy(), objective_function
                            )

                            status = model_iter.status
                            if status == GRB.OPTIMAL:
                                max_objective2 = -model_iter.objVal
                                if (
                                    np.abs(max_objective2 - max_objective)
                                    > redundant_facet_tol
                                ):
                                    redundant_facet_right = False
                                else:
                                    removed += 1
                                    facet_right_removed[0, i] = True

                        model_iter.reset()
                        x = model_iter.getVars()
                        for j in range(n):
                            x[j].LB = lb[j]
                            x[j].UB = ub[j]
                            x[j].obj = objective_function[j]

                        model_iter.optimize()

                        status = model_iter.status
                        if status == GRB.OPTIMAL:
                            min_objective = model_iter.objVal
                        else:
                            min_objective = lb[i]

                        if not facet_left_removed[0, i]:
                            lb_iter = lb.copy()
                            lb_iter[i] = lb_iter[i] - 1

                            # Call solve_lp_with_different_objectives to solve LP
                            model_iter = solve_lp_with_different_objectives(
                                model_iter.copy(), objective_function
                            )


                            status = model_iter.status
                            if status == GRB.OPTIMAL:
                                min_objective2 = model_iter.objVal
                                if (
                                    np.abs(min_objective2 - min_objective)
                                    > redundant_facet_tol
                                ):
                                    redundant_facet_left = False
                                else:
                                    removed += 1
                                    facet_left_removed[0, i] = True

                        if (not redundant_facet_left) or (not redundant_facet_right):
                            width = abs(max_objective - min_objective)

                            if width < redundant_facet_tol:
                                offset += 1
                                Aeq_res = np.vstack(
                                    (
                                        Aeq_res,
                                        A[
                                            i,
                                        ],
                                    )
                                )
                                beq_res = np.append(
                                    beq_res, min(max_objective, min_objective)
                                )
                                ub[i] = sys.float_info.max
                                lb[i] = -sys.float_info.max
                            else:
                                indices_iter.append(i)

                                if not redundant_facet_left:
                                    A_res = np.append(
                                        A_res,
                                        np.array(
                                            [
                                                A[
                                                    n + i,
                                                ]
                                            ]
                                        ),
                                        axis=0,
                                    )
                                    b_res.append(b[n + i])
                                else:
                                    lb[i] = -sys.float_info.max

                                if not redundant_facet_right:
                                    A_res = np.append(
                                        A_res,
                                        np.array(
                                            [
                                                A[
                                                    i,
                                                ]
                                            ]
                                        ),
                                        axis=0,
                                    )
                                    b_res.append(b[i])
                                else:
                                    ub[i] = sys.float_info.max
                        else:
                            ub[i] = sys.float_info.max
                            lb[i] = -sys.float_info.max

                b_res = np.asarray(b_res)
                A_res = np.asarray(A_res, dtype="float")
                A_res = np.ascontiguousarray(A_res, dtype="float")

                return A_res, b_res, Aeq_res, beq_res

    except gp.GurobiError as e:
        print("Error code " + str(e.errno) + ": " + str(e))
    except AttributeError:
        print("Gurobi solver failed.")




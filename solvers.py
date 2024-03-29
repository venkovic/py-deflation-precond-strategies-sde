import numpy as np
import scipy
from scipy import sparse
import solvers_etc
from pyamg.aggregation import smoothed_aggregation_solver 

class solver:
  """ Solves a linear system iteratively. 

      Public methods:
        set_precond, presolve, apply_invM, solve.
  """
  def __init__(self, n, solver_type, eps=1e-7, itmax=4000, W=None, ell=0):
    self.n = n
    self.type = solver_type
    self.eps = eps
    self.itmax = itmax
    
    self.ell = int(ell)
    if (self.ell < 0):
      self.ell = 0
    if (self.type == "dcg") | (self.type == "dpcg"):
      if isinstance(W, np.ndarray):
        self.W = W
        self.kdim = self.W.shape[1]
      else:
        self.W = None
        self.kdim = 0
      self.AW = None
      self.WtAW = None

  def solve(self, x0, x_sol=None):
    self.x0 = x0
    self.x = None
    if not isinstance(x_sol, np.ndarray):
      Error = False
    else:
      self.x_sol = x_sol
      self.error_Anorm = None
      Error = True
    if (self.type == "cg"):
      self.__cg(Error=Error)
    elif (self.type == "pcg"):
      self.__pcg(Error=Error)
    elif (self.type == "dcg"):
      if not isinstance(self.W, np.ndarray):
        self.__cg(Error=Error)
      else:
        r0 = self.b-self.A.dot(x0)
        self.x0 += self.W.dot(self.__apply_invWtAW(self.W.T.dot(r0)))
        self.__dcg(Error=Error)
    elif (self.type == "dpcg"):
      if not isinstance(self.W, np.ndarray):
        self.__pcg(Error=Error)
      else:
        r0 = self.b-self.A.dot(x0)
        self.x0 += self.W.dot(self.__apply_invWtAW(self.W.T.dot(r0)))
        self.__dpcg(Error=Error)

  def set_precond(self, Mat=None, precond_id=0, nb=2, application_type=1):
    self.precond_id = precond_id
    if (precond_id == 0):
      self.M = sparse.eye(self.n)
    elif (precond_id == 1):
      self.M = Mat
    elif (precond_id == 2):
      if (sparse.issparse(Mat)):
        ml = smoothed_aggregation_solver(sparse.csr_matrix(Mat))
      else:
        ml = smoothed_aggregation_solver(Mat)
      self.amg_op = ml.aspreconditioner(cycle='V')     # Inverse preconditioner, AMG operator
      self.inv_M = self.amg_op.matmat(np.eye(self.n))
      self.inv_M = (self.inv_M+self.inv_M.T)/2
      self.M = scipy.linalg.inv(self.inv_M)
      self.M = (self.M+self.M.T)/2
    elif (precond_id == 3):
      self.nb = int(nb)
      if (self.nb < 1) | (self.nb > self.n):
        self.nb = 2
      self.M = solvers_etc.get_M_bJ(Mat, self.nb)
    else:
      print('Warning: Invalid preconditioner ID.')

    if (self.precond_id != 2):
      self.application_type = application_type
      if (self.application_type == 0):
        return 
      elif (self.application_type == 1):
        if (sparse.issparse(self.M)):
          self.M_fac = sparse.linalg.factorized(sparse.csc_matrix(self.M))
          # Preconditioner application: self.M_fac(x)
        else:
          self.M_chol = scipy.linalg.cho_factor(self.M)
          # Preconditioner application: scipy.linalg.cho_solve(self.M_chol, x)
      elif (self.application_type == 2):
        if (sparse.issparse(self.M)):
          self.inv_M = sparse.linalg.inv(sparse.csc_matrix(self.M))
          # Preconditioner application: self.inv_M.dot(x)
        else:
          self.inv_M = scipy.linalg.inv(self.M)
          # Preconditioner application: self.inv_M.dot(x)
      else:
        print('Warning: Invalid application_type.')

  def presolve(self, A, b, ell=0):
    self.A = A
    self.b = b
    self.bnorm = np.linalg.norm(self.b)
    self.iterated_res_norm = None
    self.it = 0
    self.ell = int(ell)
    if (self.ell > 0):
      self.P = np.zeros((self.n,self.ell))
    if (self.type == "dcg"):
      if isinstance(self.W, np.ndarray):
        self.AW = self.A.dot(self.W)
        self.WtAW = self.W.T.dot(self.AW)
        self.__set_factorization_WtAW()
    elif (self.type == "dpcg"):
      if isinstance(self.W, np.ndarray):
        self.AW = self.A.dot(self.W)
        self.WtAW = self.W.T.dot(self.AW)
        self.__set_factorization_WtAW()

  def __set_factorization_WtAW(self, application_type=2):
    self.invWtAW_application_type = application_type
    if (self.invWtAW_application_type == 1):
      self.WtAW_chol = scipy.linalg.cho_factor(self.WtAW)
      # Application: scipy.linalg.cho_solve(self.WtAW_chol, x)
    elif (self.invWtAW_application_type == 2):
      if (sparse.issparse(self.WtAW)):
        self.inv_WtAW = sparse.linalg.inv(sparse.csc_matrix(self.WtAW))
      else:
        self.inv_WtAW = scipy.linalg.inv(self.WtAW)

  def apply_invM(self, x):
    if (self.precond_id == 2):
      return self.amg_op(x)
    else:
      if (self.application_type == 0):
        if (sparse.issparse(self.M)):
          return sparse.linalg.spsolve(self.M, x)
        else:
          return scipy.linalg.solve(self.M, x)
      elif (self.application_type == 1):
        if (sparse.issparse(self.M)):
          return self.M_fac(x)
        else:
          return scipy.linalg.cho_solve(self.M_chol, x)
      elif (self.application_type == 2):
        return self.inv_M.dot(x)
  
  def get_deflated_op(self):
    if (self.invWtAW_application_type == 0):
      HtA = self.A.copy().tolil()
      for j in range(self.n):
        HtA[:,j] -= (self.AW.dot(self.__apply_invWtAW(self.AW.T[:,j]))).reshape((self.n,1))
    elif (self.invWtAW_application_type == 1):
      HtA = self.A.copy().tolil()
      for j in range(self.n):
        HtA[:,j] -= (self.AW.dot(self.__apply_invWtAW(self.AW.T[:,j]))).reshape((self.n,1))
    elif (self.invWtAW_application_type == 2):
      HtA = self.A-self.AW.dot(self.inv_WtAW.dot(self.AW.T))
    return HtA

  def get_chol_M(self):
    if (self.precond_id == 2):
      self.L_M = scipy.linalg.cholesky(self.M).T
    elif (self.precond_id == 1) | (self.precond_id == 3):
      if (len(self.M.todia().offsets) == 3):
        Mb = [[0]+list(self.M.diagonal(1)), list(self.M.diagonal(0))]
        _diags = scipy.linalg.cholesky_banded(Mb)
        self.L_M = sparse.diags([_diags[0,1:], _diags[1,:]], (-1,0))
      else:
        raise ValueError("Preconditioner expected to be tridiagonal.")
    if (sparse.issparse(self.L_M)):
      self.invL_M = sparse.linalg.inv(sparse.csc_matrix(self.L_M))
    else:
      self.invL_M = scipy.linalg.inv(self.L_M)

  def __apply_invWtAW(self, x):
    if (self.invWtAW_application_type == 0):
      if (sparse.issparse(self.WtAW)):
        return sparse.linalg.spsolve(self.WtAW, x)
      else:
        return scipy.linalg.solve(self.WtAW, x)
    elif (self.invWtAW_application_type == 1):
      return scipy.linalg.cho_solve(self.WtAW_chol, x)
    elif (self.invWtAW_application_type == 2):
      return self.inv_WtAW.dot(x)

  def __cg(self, Error=False):
    self.it = 0
    self.x = np.copy(self.x0)
    r = self.b-self.A.dot(self.x)
    rTr = r.dot(r)
    p = np.copy(r)
    self.iterated_res_norm = [np.sqrt(rTr)]
    if (Error):
      err = self.x-self.x_sol
      self.error_Anorm += [np.sqrt(err.dot(A.dot(err)))]
    tol = self.eps*self.bnorm
    while (self.it < self.itmax) & (self.iterated_res_norm[-1] > tol):
      Ap = self.A.dot(p)
      d = Ap.dot(p)
      alpha = rTr/d
      beta = 1./rTr
      self.x += alpha*p
      r -= alpha*Ap
      if (Error):
  	    err = self.x-self.x_sol
  	    self.error_Anorm += [np.sqrt(err.dot(A.dot(err)))]
      rTr = r.dot(r)
      beta *= rTr
      if (self.it < self.ell): 
        self.P[:,self.it] = p
      p = r+beta*p
      self.iterated_res_norm += [np.sqrt(rTr)]
      self.it += 1
    if (self.it < self.ell):
      self.P = self.P[:,:self.it]
      self.ell = self.it

  def __pcg(self, Error=False):
    self.it = 0
    self.x = np.copy(self.x0)
    r = self.b-self.A.dot(self.x)
    rTr = r.dot(r)
    z = self.apply_invM(r)
    rTz = r.dot(z)
    p = np.copy(z)
    self.iterated_res_norm = [np.sqrt(rTr)]
    if (Error):
      err = self.x-self.x_sol
      self.error_Anorm += [np.sqrt(err.dot(A.dot(err)))]
    tol = self.eps*self.bnorm
    while (self.it < self.itmax) & (self.iterated_res_norm[-1] > tol):
      Ap = self.A.dot(p)
      d = Ap.dot(p)
      alpha = rTz/d
      beta = 1./rTz
      self.x += alpha*p
      r -= alpha*Ap
      if (Error):
        err = self.x-self.x_sol
        self.error_Anorm += [np.sqrt(err.dot(A.dot(err)))]
      rTr = r.dot(r)
      z = self.apply_invM(r)
      rTz = r.dot(z)
      beta *= rTz
      if (self.it < self.ell): 
        self.P[:,self.it] = p
      p = z+beta*p
      self.iterated_res_norm += [np.sqrt(rTr)]
      self.it += 1
    if (self.it < self.ell):
      self.P = self.P[:,:self.it]
      self.ell = self.it

  def __dcg(self, Error=False, Reortho=False):
    self.it = 0
    self.x = np.copy(self.x0)
    r = self.b-self.A.dot(self.x)
    if (Reortho):
      R = (self.W.dot(np.linalg.inv(self.W.T.dot(self.W)))).dot(self.W.T)
      r -= R.dot(r)
    rTr = r.dot(r)
    hmu = self.__apply_invWtAW(self.AW.T.dot(r))
    p = r-self.W.dot(hmu)
    self.iterated_res_norm = [np.sqrt(rTr)]
    if (Error):
      err = self.x-self.x_sol
      self.error_Anorm += [np.sqrt(err.dot(A.dot(err)))]
    tol = self.eps*self.bnorm
    while (self.it < self.itmax) & (self.iterated_res_norm[-1] > tol):
      Ap = self.A.dot(p)
      d = Ap.dot(p)
      alpha = rTr/d
      beta = 1./rTr
      self.x += alpha*p
      r -= alpha*Ap
      if (Error):
        err = self.x-self.x_sol
        self.error_Anorm += [np.sqrt(err.dot(A.dot(err)))]
      if (Reortho): 
        r -= R.dot(r)
      rTr = r.dot(r)  
      beta *= rTr
      hmu = self.__apply_invWtAW(self.AW.T.dot(r))
      if (self.it < self.ell):
        self.P[:,self.it] = p
      p = beta*p+r-self.W.dot(hmu)
      self.iterated_res_norm += [np.sqrt(rTr)]
      self.it += 1
    if (self.it < self.ell): 
      self.P = self.P[:,:self.it]
      self.ell = self.it

  def __dpcg(self, Error=False, Reortho=False):
    self.it = 0
    self.x = np.copy(self.x0)
    r = self.b-self.A.dot(self.x)
    if (Reortho):
      R = (self.W.dot(np.linalg.inv(self.W.T.dot(self.W)))).dot(self.W.T)
      r -= R.dot(r)
    rTr = r.dot(r)
    z = self.apply_invM(r)
    rTz = r.dot(z)
    hmu = self.__apply_invWtAW(self.AW.T.dot(z))
    p = z-self.W.dot(hmu)
    self.iterated_res_norm = [np.sqrt(rTr)]
    if (Error):
      err = self.x-self.x_sol
      self.error_Anorm += [np.sqrt(err.dot(A.dot(err)))]
    tol = self.eps*self.bnorm
    while (self.it < self.itmax) & (self.iterated_res_norm[-1] > tol):
      Ap = self.A.dot(p)
      d = Ap.dot(p)
      alpha = rTz/d
      beta = 1./rTz
      self.x += alpha*p
      r -= alpha*Ap
      if (Error):
        err = self.x-self.x_sol
        self.error_Anorm += [np.sqrt(err.dot(A.dot(err)))]
      if (Reortho): 
        r -= R.dot(r)
      rTr = r.dot(r)  
      z = self.apply_invM(r)
      rTz = r.dot(z)
      beta *= rTz
      hmu = self.__apply_invWtAW(self.AW.T.dot(z))
      if (self.it < self.ell):
        self.P[:,self.it] = p
      p = beta*p+z-self.W.dot(hmu)
      self.iterated_res_norm += [np.sqrt(rTr)]
      self.it += 1
    if (self.it < self.ell): 
      self.P = self.P[:,:self.it]
      self.ell = self.it
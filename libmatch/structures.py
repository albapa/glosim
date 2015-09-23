#!/usr/bin/env python
# Computes the matrix of similarities between structures in a xyz file
# by first getting SOAP descriptors for all environments, finding the best
# match between environments using the Hungarian algorithm, and finally
# summing up the environment distances.
# Supports periodic systems, matching between structures with different
# atom number and kinds, and sports the infrastructure for introducing an
# alchemical similarity kernel to match different atomic species

import sys
import quippy
from lap.lap import best_pairs
import numpy as np
from environments import environ, alchemy, envk
__all__ = [ "structk", "gstructk", "structure" ]

   
class structure:
   def __init__(self, salchem=None):
      self.env={}
      self.species={}
      self.zspecies = []
      self.nenv=0  
      self.alchem=salchem
      if self.alchem is None: self.alchem=alchemy()
      self.globenv = None
      
   def getnz(self, sp):
      if sp in self.species:
         return self.species[sp]
      else: return 0
      
   def getenv(self, sp, i):
      if sp in self.env and i<len(self.env[sp]):
         return self.env[sp][i]
      else: 
         return environ(self.nmax,self.lmax,self.alchem,sp)  # missing atoms environments just returned as isolated species!
         
   def ismissing(self, sp, i):
      if sp in self.species and i<self.species[sp]:
         return False
      else: return True
   
      
   def parse(self, fat, coff=5.0, nmax=4, lmax=3, gs=0.5, cw=1.0, nocenter=[], noatom=[], kit=None):
      """ Takes a frame in the QUIPPY format and computes a list of its environments. """
      
      # removes atoms that are to be ignored
      at = fat.copy()
      nol = []
      for s in range(1,at.z.size+1):
         if at.z[s] in noatom: nol.append(s)
      if len(nol)>0: at.remove_atoms(nol)
      
      self.nmax = nmax
      self.lmax = lmax
      self.species = {}
      for z in at.z:      
         if z in self.species: self.species[z]+=1
         else: self.species[z] = 1
            
      self.zspecies = self.species.keys();
      self.zspecies.sort(); 
      lspecies = 'n_species='+str(len(self.zspecies))+' species_Z={ '
      for z in self.zspecies: lspecies = lspecies + str(z) + ' '
      lspecies = lspecies + '}'
   
      at.set_cutoff(coff);
      at.calc_connect();
      
      self.nenv = 0
      for sp in self.species:
         if sp in nocenter: 
            self.species[sp]=0
            continue # Option to skip some environments
         
         # first computes the descriptors of species that are present
         desc = quippy.descriptors.Descriptor("soap central_weight="+str(cw)+"  covariance_sigma0=0.0 atom_sigma="+str(gs)+" cutoff="+str(coff)+" n_max="+str(nmax)+" l_max="+str(lmax)+' '+lspecies+' Z='+str(sp) )   
         psp=np.asarray(desc.calc(at,desc.dimensions(),self.species[sp])).T;
      
         # now repartitions soaps in environment descriptors
         lenv = []
         for p in psp:
            nenv = environ(nmax, lmax, self.alchem)
            nenv.convert(sp, self.zspecies, p)
            lenv.append(nenv)
         self.env[sp] = lenv
         self.nenv += self.species[sp]
         
      # adds kit data   
      if kit is None: kit = {}
      
      for sp in kit:
         if not sp in self.species: 
            self.species[sp]=0
            self.env[sp] = []
         for k in range(self.species[sp], kit[sp]):
            self.env[sp].append(environ(self.nmax,self.lmax,self.alchem,sp))
            self.nenv+=1
         self.species[sp] = kit[sp]          
      
      self.zspecies = self.species.keys();
      self.zspecies.sort(); 
      
      # also compute the global (flattened) fingerprint
      self.globenv = environ(nmax, lmax, self.alchem)
      for k, se in self.env.items():
         for e in se:
            self.globenv.add(e)


def gcd(a,b):
   if (b>a): a,b = b, a
   
   while (b):  a, b = b, a%b
   
   return a
   
def lcm(a,b):
   return a*b/gcd(b,a)

def gstructk(strucA, strucB, alchem=alchemy(), periodic=False):
    
   return envk(strucA.globenv, strucB.globenv, alchem) 

def structk(strucA, strucB, alchem=alchemy(), periodic=False, mode="sumlog", fout=None):
   nenv = 0
   
   if periodic: # replicate structures to match structures of different periodicity
      # we do not check for compatibility at this stage, just assume that the 
      # matching will be done somehow (otherwise it would be exceedingly hard to manage in case of non-standard alchemy)
      nspeciesA = []
      nspeciesB = []
      for z in strucA.zspecies:
         nspeciesA.append( (z, strucA.getnz(z)) )
      for z in strucB.zspecies:
         nspeciesB.append( (z, strucB.getnz(z)) )
      nenvA = strucA.nenv
      nenvB = strucB.nenv      
   else:   
      # top up missing atoms with isolated environments
      # first checks whic atoms are present
      zspecies = sorted(list(set(strucB.zspecies+strucA.zspecies)))
      nspecies = []
      for z in zspecies:
         nz = max(strucA.getnz(z),strucB.getnz(z))
         nspecies.append((z,nz)) 
         nenv += nz
      nenvA = nenvB = nenv
      nspeciesA = nspeciesB = nspecies
      
   if mode=="average":
       genvA=strucA.globenv
       genvB=strucB.globenv
        
       gk = envk(genvA, genvB, alchem)
       
   np.set_printoptions(linewidth=500,precision=4)

   kk = np.zeros((nenvA,nenvB),float)
   ika = 0
   ikb = 0   
   for za, nza in nspeciesA:
      for ia in xrange(nza):
         envA = strucA.getenv(za, ia)         
         ikb = 0
         for zb, nzb in nspeciesB:
            acab = alchem.getpair(za,zb)
            for ib in xrange(nzb):
               envB = strucB.getenv(zb, ib)
               if alchem.mu > 0 and (strucA.ismissing(za, ia) ^ strucB.ismissing(zb, ib)):
                  if mode == "kdistance" or mode == "nkdistance":  # includes a penalty dependent on "mu", in a way that is consistent with the definition of kernel distance
                     kk[ika,ikb] = acab - alchem.mu/2  
                  else:
                     kk[ika,ikb] = np.exp(-alchem.mu) * acab 
               else:
                  kk[ika,ikb] = envk(envA, envB, alchem) * acab
               ikb+=1
         ika+=1

   if fout != None:
      # prints out similarity information for the environment pairs
      fout.write("# atomic species in the molecules (possibly topped up with dummy isolated atoms): \n")      
      for za, nza in nspeciesA:
         for ia in xrange(nza): fout.write(" %d " % (za) )
      fout.write("\n");
      for zb, nzb in nspeciesB:
         for ib in xrange(nzb): fout.write(" %d " % (zb) )
      fout.write("\n");
      
      fout.write("# environment kernel matrix: \n")      
      for r in kk:
         for e in r:
            fout.write("%8.4e " % (e) )
         fout.write("\n")
       
   if periodic: 
      # now we replicate the (possibly rectangular) matrix to make
      # a square matrix for matching
      nenv = lcm(nenvA, nenvB)
      skk = np.zeros((nenv, nenv), float)
      for i in range(nenv/nenvA):
         for j in range(nenv/nenvB):
            skk[i*nenvA:(i+1)*nenvA,j*nenvB:(j+1)*nenvB] = kk
      kk = skk
      
   # Now we have the matrix of scalar products. 
   # We can first find the optimal scalar product kernel
   # we must find the maximum "cost"
   if mode == "logsum":
      hun=best_pairs(1.0-kk)
   
      dotcost = 0.0
      for pair in hun:
         dotcost+=kk[pair[0],pair[1]]
      cost = -np.log(dotcost/nenv)
   elif mode == "kdistance" or mode == "nkdistance":
      dk = 2*(1-kk)
      hun=best_pairs(dk)
      distcost = 0.0
      for pair in hun:
         distcost+=dk[pair[0],pair[1]]
      if periodic or mode == "nkdistance":
         # kdistance is extensive, nkdistance (or periodic matching) is intensive
         distcost*=1.0/nenv
      cost = distcost # this is really distance ^ 2      
   elif mode == "sumlog":   
      dk = (kk +1e-100)/(1+1e-100)  # avoids inf...
      dk = -np.log(dk)
      #print dk
      hun=best_pairs(dk)
      distcost = 0.0
      for pair in hun:
         distcost+=dk[pair[0],pair[1]]
      if periodic:    
         # here we normalize by number of environments only when doing 
         # periodic matching, so that otherwise the distance is extensive
         distcost*=1.0/nenv
      cost = distcost
   elif mode == "permanent":
      from permanent import permanent
      perm=permanent(np.array(kk,dtype=complex))       
      return perm.real/np.math.factorial(nenv)/nenv
   else: raise ValueError("Unknown global fingerprint mode ", mode)
   
   if fout != None:
      fout.write("# optimal environment list: \n")      
      for pair in hun:
         fout.write("%d  %d  \n" % (pair[0],pair[1]) )
      fout.close()
   
   if cost<0.0: 
    #  print >> sys.stderr, "\n WARNING: negative squared distance ", cost, "\n"
      return 0.0 
   else: return np.sqrt(cost)

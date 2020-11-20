import sys
import random
import pathlib
import os
import time
from datetime import datetime
import platform
current_file_path = pathlib.Path(__file__).parent.absolute()
sys.path.insert(1,current_file_path)
if platform.system() == 'Windows':
	#sys.path.insert(1,os.path.join(current_file_path,'..','..','fuzzy','build','x64-Debug'))
	sys.path.insert(1,os.path.join(current_file_path,'..','build','binds','Release'))
else:
	sys.path.insert(1,os.path.join(current_file_path,'..','build','binds'))
	sys.path.insert(1,os.path.join(current_file_path,'..','..','fuzzy','build'))
from CPPYABM import Agent
from fuzzy import fuzzy

random.seed(datetime.now())
class Dead(Agent):
	"""
	This class describes a Dead cell.
	"""
	def __init__(self,env,configs = None, params = None):
		super().__init__(env = env, class_name = 'Dead')
		self.configs = configs or {}
		self.params = params or {}
		

	def step(self):
		pass


class MSC(Agent):
	"""
	This class describes a MSC cell.
	"""
	def __init__(self,env,configs = None, params = None, id_ = 0):
		Agent.__init__(self,env = env, class_name = 'MSC')
		self.configs = configs or {}
		self.id = id_
		self.params = params or {}
		self.policy = fuzzy("MSC",self.params)
		self.data = {}
		## initialize
		for key,value in self.configs['attrs'].items():
			self.data[key] = value;
	def inherit(self,father):
		self.data = father.data
	def step(self):
		predictions = self.run_policy()
		if (self.patch.data["agent_density"] == 0):
			print(len(self.patch.find_neighbor_agents(include_self = True))/9.0)

		die = self.mortality(predictions["Mo"])
		hatch = self.proliferation(predictions["Pr"])
		walk = self.migration(predictions["Mi"])
		AE,adapted_ph = self.alkalinity()
		MI = self.MI(predictions["Pr"]);
		if walk:
			self.order_move(quiet = True, reset = True)
		if hatch:
			self.order_hatch(quiet = True, inherit = True)
		if die:
			self.order_switch("Dead")
		self.data["MI"] = MI
		self.data["pH"] = adapted_ph
		pass 

	def proliferation(self,Pr):
		normOrder = self.params["Pr_N_v"]
		baseChance = self.params["B_MSC_Pr"]
		change =(Pr / normOrder) * baseChance
		pick = random.random()
		if pick < change:
			return True
		else:
			return False

	def migration(self, Mi):
		chance = Mi
		pick = random.random()
		if pick < chance:
			return True
		else:
			return False
	def MI(self,Pr):
		return Pr		
	def run_policy(self):
		"""
		Collects policy inputs, executes policy and returns predictions
		"""
		AE, new_adapted_ph = self.alkalinity()
		CD = self.patch.data["agent_density"]
		Mg = self.patch.data["Mg"]/self.params["Mg_max"]
		policy_inputs = {"AE":AE, "Mg":Mg, "CD": CD}
		# print(policy_inputs)
		# print(policy_inputs)
		predictions = self.policy.predict(policy_inputs) # fuzzy controller
		# print(predictions)
		# sys.exit(0)
		return predictions
		pass

	def alkalinity(self):
		"""
		Calculates alkalinity (AE)
		"""
		adapted_pH = self.data["pH"]
		env_pH = self.patch.data["pH"]
		# if adapted_pH == 0:
		# 	AE = 1
		# else:
		AE = abs(env_pH - adapted_pH) / adapted_pH
		if AE > 1:
			AE = 1
		new_adapted_pH = 0
		adaptation_rate = self.params["B_MSC_rec"]
		if env_pH > adapted_pH:
			new_adapted_pH = adapted_pH + adaptation_rate
		else:
			new_adapted_pH = adapted_pH - adaptation_rate
		# if (AE == 0):
		# 	print("adapted_pH: {} env_pH {} AE {} new_adapted_pH {}".format(adapted_pH,env_pH,AE,new_adapted_pH))
		return AE, new_adapted_pH
	
	def mortality(self,Mo):
		maxOrder = self.params["Mo_H_v"]
		baseChance = self.params["B_MSC_Mo"]
		change =(1+Mo*maxOrder) * baseChance
		pick = random.random()
		if pick < change:
			return "Dead"
		else:
			return False
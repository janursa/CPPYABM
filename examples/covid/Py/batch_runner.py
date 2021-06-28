import time
import os
# from pprogress import ProgressBar
import json
from covidmodel_original import CovidModel
from covidmodel_original import *
import sys
import pandas as pd

class Runner:

    def __init__(self,model_class,args,runs,parallel=False):
        self.model_class = model_class
        self.args = args
        self.runs = runs
        if parallel:
            from mpi4py import MPI
            self.comm = MPI.COMM_WORLD
            self.rank = self.comm.Get_rank()
        else:
            self.rank = 0
        if self.rank == 0:
            print("Number of CPUs assigned: ",self.comm.Get_size())
    def run(self):
        if self.rank == 0:
            import numpy as np
            CPU_n = self.comm.Get_size()
            shares = np.ones(CPU_n,dtype=int)*int(int(self.runs)/CPU_n)
            plus = self.runs%CPU_n
            for i in range(plus):
                shares[i]+=1

            portions = []
            for i in range(CPU_n):
                start = sum(shares[0:i])
                end = start + shares[i]
                portions.append([start,end])
            

        else:
            portions = None
            paramsets = None

        portion = self.comm.scatter(portions,root = 0)    
        

        def run_model(start,end):

            outputs = []
            for i in range(start,end):
                model = self.model_class(**self.args)
                output = model.episode()
                outputs.append(output)

            return outputs
        outputs_perCore = run_model(portion[0],portion[1])
        outputs_stacks = self.comm.gather(outputs_perCore,root = 0)
        if self.rank == 0:
            import numpy as np
            outputs = np.array([])
            for stack in outputs_stacks:
                outputs = np.concatenate([outputs,stack],axis = 0)
            keys = outputs[0].keys()
            cumulated_data = {}
            for key in keys:
                aa = []
                for output in outputs:
                    aa += output[key]
                cumulated_data.update({key:aa}) 
            cumulated_data = pd.DataFrame(cumulated_data)
            cumulated_data.to_csv('batch_outputs.csv')
            # np.savetxt('batch_outputs.txt',np.array(outputs),fmt='%s')
if __name__ == '__main__':
    file_params = sys.argv[1]
    with open(file_params) as f:
        data = json.load(f)
    age_mortality = {
        AgeGroup.C80toXX: data["model"]["mortalities"]["age"]["80+"],
        AgeGroup.C70to79: data["model"]["mortalities"]["age"]["70-79"],
        AgeGroup.C60to69: data["model"]["mortalities"]["age"]["60-69"],
        AgeGroup.C50to59: data["model"]["mortalities"]["age"]["50-59"],
        AgeGroup.C40to49: data["model"]["mortalities"]["age"]["40-49"],
        AgeGroup.C30to39: data["model"]["mortalities"]["age"]["30-39"],
        AgeGroup.C20to29: data["model"]["mortalities"]["age"]["20-29"],
        AgeGroup.C10to19: data["model"]["mortalities"]["age"]["10-19"],
        AgeGroup.C00to09: data["model"]["mortalities"]["age"]["00-09"],
    }

    # Observed distribution of mortality rage per sex
    sex_mortality = {
        SexGroup.MALE: data["model"]["mortalities"]["sex"]["male"],
        SexGroup.FEMALE: data["model"]["mortalities"]["sex"]["female"],
    }

    age_distribution = {
        AgeGroup.C80toXX: data["model"]["distributions"]["age"]["80+"],
        AgeGroup.C70to79: data["model"]["distributions"]["age"]["70-79"],
        AgeGroup.C60to69: data["model"]["distributions"]["age"]["60-69"],
        AgeGroup.C50to59: data["model"]["distributions"]["age"]["50-59"],
        AgeGroup.C40to49: data["model"]["distributions"]["age"]["40-49"],
        AgeGroup.C30to39: data["model"]["distributions"]["age"]["30-39"],
        AgeGroup.C20to29: data["model"]["distributions"]["age"]["20-29"],
        AgeGroup.C10to19: data["model"]["distributions"]["age"]["10-19"],
        AgeGroup.C00to09: data["model"]["distributions"]["age"]["00-09"],
    }

    # Observed distribution of mortality rage per sex
    sex_distribution = {
        SexGroup.MALE: data["model"]["distributions"]["sex"]["male"],
        SexGroup.FEMALE: data["model"]["distributions"]["sex"]["female"],
    }
    # Value distribution per stage per interaction (micro vs macroeconomics)
    value_distibution = {
        ValueGroup.PRIVATE: {
            Stage.SUSCEPTIBLE: data["model"]["value"]["private"]["susceptible"],
            Stage.EXPOSED: data["model"]["value"]["private"]["exposed"],
            Stage.SYMPDETECTED: data["model"]["value"]["private"]["sympdetected"],
            Stage.ASYMPTOMATIC: data["model"]["value"]["private"]["asymptomatic"],
            Stage.ASYMPDETECTED: data["model"]["value"]["private"]["asympdetected"],
            Stage.SEVERE: data["model"]["value"]["private"]["severe"],
            Stage.RECOVERED: data["model"]["value"]["private"]["recovered"],
            Stage.DECEASED: data["model"]["value"]["private"]["deceased"]
        },
        ValueGroup.PUBLIC: {
            Stage.SUSCEPTIBLE: data["model"]["value"]["public"]["susceptible"],
            Stage.EXPOSED: data["model"]["value"]["public"]["exposed"],
            Stage.SYMPDETECTED: data["model"]["value"]["public"]["sympdetected"],
            Stage.ASYMPTOMATIC: data["model"]["value"]["public"]["asymptomatic"],
            Stage.ASYMPDETECTED: data["model"]["value"]["public"]["asympdetected"],
            Stage.SEVERE: data["model"]["value"]["public"]["severe"],
            Stage.RECOVERED: data["model"]["value"]["public"]["recovered"],
            Stage.DECEASED: data["model"]["value"]["public"]["deceased"]
        }
    }
    model_params = {
        "num_agents": data["model"]["epidemiology"]["num_agents"],
        "width": data["model"]["epidemiology"]["width"],
        "height": data["model"]["epidemiology"]["height"],
        "repscaling": data["model"]["epidemiology"]["repscaling"],
        "kmob": data["model"]["epidemiology"]["kmob"],
        "age_mortality": age_mortality,
        "sex_mortality": sex_mortality,
        "age_distribution": age_distribution,
        "sex_distribution": sex_distribution,
        "prop_initial_infected": data["model"]["epidemiology"]["prop_initial_infected"],
        "rate_inbound": data["model"]["epidemiology"]["rate_inbound"],
        "avg_incubation_time": data["model"]["epidemiology"]["avg_incubation_time"],
        "avg_recovery_time": data["model"]["epidemiology"]["avg_recovery_time"],
        "proportion_asymptomatic": data["model"]["epidemiology"]["proportion_asymptomatic"],
        "proportion_severe": data["model"]["epidemiology"]["proportion_asymptomatic"],
        "prob_contagion": data["model"]["epidemiology"]["proportion_asymptomatic"],
        "proportion_beds_pop": data["model"]["epidemiology"]["proportion_beds_pop"],
        "proportion_isolated": data["model"]["policies"]["isolation"]["proportion_isolated"],
        "day_start_isolation": data["model"]["policies"]["isolation"]["day_start_isolation"],
        "days_isolation_lasts": data["model"]["policies"]["isolation"]["days_isolation_lasts"],
        "after_isolation": data["model"]["policies"]["isolation"]["after_isolation"],
        "prob_isolation_effective": data["model"]["policies"]["isolation"]["prob_isolation_effective"],
        "social_distance": data["model"]["policies"]["distancing"]["social_distance"],
        "day_distancing_start": data["model"]["policies"]["distancing"]["day_distancing_start"],
        "days_distancing_lasts": data["model"]["policies"]["distancing"]["days_distancing_lasts"],
        "proportion_detected": data["model"]["policies"]["testing"]["proportion_detected"],
        "day_testing_start": data["model"]["policies"]["testing"]["day_testing_start"],
        "days_testing_lasts": data["model"]["policies"]["testing"]["days_testing_lasts"],
        "day_tracing_start": data["model"]["policies"]["tracing"]["day_tracing_start"],
        "days_tracing_lasts": data["model"]["policies"]["tracing"]["days_tracing_lasts"],
        "new_agent_proportion": data["model"]["policies"]["massingress"]["new_agent_proportion"],
        "new_agent_start": data["model"]["policies"]["massingress"]["new_agent_start"],
        "new_agent_lasts": data["model"]["policies"]["massingress"]["new_agent_lasts"],
        "new_agent_age_mean": data["model"]["policies"]["massingress"]["new_agent_age_mean"],
        "new_agent_prop_infected": data["model"]["policies"]["massingress"]["new_agent_prop_infected"],
        "stage_value_matrix": value_distibution,
        "test_cost": data["model"]["value"]["test_cost"],
        "alpha_private": data["model"]["value"]["alpha_private"],
        "alpha_public": data["model"]["value"]["alpha_public"],
        "steps":data['ensemble']['steps']
    }
    begin = time.time()
    runner_obj = Runner(CovidModel,model_params,runs = data['ensemble']['runs'], parallel=True)
    runner_obj.run()
    end = time.time()
    print('Running completed in {} seconds'.format(end-begin))
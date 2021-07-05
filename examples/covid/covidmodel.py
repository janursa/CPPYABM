# Santiago Nunez-Corrales and Eric Jakobsson
# Illinois Informatics and Molecular and Cell Biology
# University of Illinois at Urbana-Champaign
# {nunezco,jake}@illinois.edu

# A simple tunable model for COVID-19 response
import time
import random
import sys, os,pathlib
import matplotlib.pyplot as plt
current_file_path = pathlib.Path(__file__).parent.absolute()
sys.path.insert(1,os.path.join(current_file_path,'../..','build'))
from cppyabm.binds import Env, Agent, Patch, space
from scipy.stats import poisson, bernoulli
from enum import Enum
import numpy as np
import random
import sys
import os, psutil


class Stage(Enum):
    SUSCEPTIBLE = 1
    EXPOSED = 2
    ASYMPTOMATIC = 3
    SYMPDETECTED = 4
    ASYMPDETECTED = 5
    SEVERE = 6
    RECOVERED = 7
    DECEASED = 8


class AgeGroup(Enum):
    C00to09 = 0
    C10to19 = 1
    C20to29 = 2
    C30to39 = 3
    C40to49 = 4
    C50to59 = 5
    C60to69 = 6
    C70to79 = 7
    C80toXX = 8


class SexGroup(Enum):
    MALE = 1
    FEMALE = 2


class ValueGroup(Enum):
    PRIVATE = 1
    PUBLIC = 2 


class CovidAgent(Agent):
    """ An agent representing a potential covid case"""
    
    def __init__(self, model, name, ageg, sexg, mort):
        super().__init__(model, name)
        self.stage = Stage.SUSCEPTIBLE
        self.age_group = ageg
        self.sex_group = sexg
        # These are fixed values associated with properties of individuals
        self.incubation_time = poisson.rvs(model.avg_incubation)
        self.dwelling_time = poisson.rvs(model.avg_dwell)
        self.recovery_time = poisson.rvs(model.avg_recovery)
        self.prob_contagion = self.env.prob_contagion_base
        # Mortality in vulnerable population appears to be around day 2-3
        self.mortality_value = mort/(self.env.dwell_15_day*self.recovery_time)
        # Severity appears to appear after day 5
        self.severity_value = model.prob_severe/(self.env.dwell_15_day*self.recovery_time)
        self.curr_dwelling = 0
        self.curr_incubation = 0
        self.curr_recovery = 0
        self.curr_asymptomatic = 0
        # Isolation measures are set at the model step level
        self.isolated = False
        self.isolated_but_inefficient = False
        # Contagion probability is local
        self.test_chance = 0
        # Horrible hack for isolation step
        self.in_isolation = False
        self.in_distancing = False
        self.in_testing = False
        self.astep = 0
        self.tested = False
        # Economic assumptions
        self.cumul_private_value = 0
        self.cumul_public_value = 0
        # Employment
        self.employed = True
        # Contact tracing: this is only available for symptomatic patients
        self.tested_traced = False
        # All agents 
        self.contacts = set()
        # We assume it takes two full days
        self.tracing_delay = 2*model.dwell_15_day
        self.tracing_counter = 0
        
    def alive(self):
        print(f'{self.unique_id} {self.age_group} {self.sex_group} is alive')

    def is_contagious(self):
        return (self.stage == Stage.EXPOSED) or (self.stage == Stage.ASYMPTOMATIC)

    def dmult(self):
        # In this function, we simulate aerosol effects exhibited by droplets due to
        # both the contributions of a) a minimum distance with certainty of infection
        # and a the decreasing bioavailability of droplets, modeled as a sigmoid function.
        # Units are in meters. We assume that after 1.5 meter bioavailability decreases as a
        # sigmoid. This case supposses infrequent sneezing, but usual saliva droplets when
        # masks are not in use. A multiplier of k = 10 is used as a sharpening parameter
        # of the distribution and must be further callibrated.
        mult = 1.0

        if self.env.distancing >= 1.5:
            k = 10
            mult = 1.0 - (1.0 / (1.0 + np.exp(k*(-(self.env.distancing - 1.5) + 0.5))))

        return mult

    # In this function, we count effective interactants
    def interactants(self):
        count = 0

        if (self.stage != Stage.DECEASED) and (self.stage != Stage.RECOVERED):
            for agent in self.get_patch().get_agents():
                if self != agent: #TODO: check this out
                    if not(agent.isolated) or self.isolated_but_inefficient:
                        count = count + 1

        return count

    # A function that applies a contact tracing test
    def test_contact_trace(self):
        # We may have an already tested but it had a posterior contact and became infected
        if self.stage == Stage.SUSCEPTIBLE:
            self.tested_traced = True
        elif self.stage == Stage.EXPOSED:
            self.tested_traced = True

            if bernoulli.rvs(self.env.prob_asymptomatic):
                    self.stage = Stage.ASYMPDETECTED
            else:
                self.stage = Stage.SYMPDETECTED
        elif self.stage == Stage.ASYMPTOMATIC:
            self.stage = Stage.ASYMPDETECTED
            self.tested_traced = True
        else:
            return

    def add_contact_trace(self, other):
        if self.env.tracing_now:
            self.contacts.add(other)

    def step(self):
        # We compute unemployment in general as a probability of 0.00018 per day.
        # In 60 days, this is equivalent to a probability of 1% unemployment filings.
        if self.employed:
            if self.isolated:
                if bernoulli.rvs(32*0.00018/self.env.dwell_15_day):
                    self.employed = False
            else:
                if bernoulli.rvs(8*0.00018/self.env.dwell_15_day):
                    self.employed = False

        # We also compute the probability of re-employment, which is at least ten times
        # as smaller in a crisis.
        if not(self.employed):
            if bernoulli.rvs(0.000018/self.env.dwell_15_day):
                self.employed = True

        # Social distancing
        if not(self.in_distancing) and (self.astep >= self.env.distancing_start):
            self.prob_contagion = self.dmult() * self.env.prob_contagion_base
            self.in_distancing = True

        if self.in_distancing and (self.astep >= self.env.distancing_end):
            self.prob_contagion = self.env.prob_contagion_base
            self.in_distancing = False

        # Testing
        if not(self.in_testing) and (self.astep >= self.env.testing_start):
            self.test_chance = self.env.testing_rate
            self.in_testing = True

        if self.in_testing and (self.astep >= self.env.testing_end):
            self.test_chance = 0
            self.in_testing = False

        # Self isolation is tricker. We only isolate susceptibles, incubating and asymptomatics
        if not(self.in_isolation):
            if (self.astep >= self.env.isolation_start):
                if (self.stage == Stage.SUSCEPTIBLE) or (self.stage == Stage.EXPOSED) or \
                    (self.stage == Stage.ASYMPTOMATIC):
                    if bool(bernoulli.rvs(self.env.isolation_rate)):
                        self.isolated = True
                    else:
                        self.isolated = False
                    self.in_isolation = True
            elif (self.astep >= self.env.isolation_end):
                if (self.stage == Stage.SUSCEPTIBLE) or (self.stage == Stage.EXPOSED) or \
                    (self.stage == Stage.ASYMPTOMATIC):
                    if bool(bernoulli.rvs(self.env.after_isolation)):
                        self.isolated = True
                    else:
                        self.isolated = False
                    self.in_isolation = True

                    
        # Using a similar logic, we remove isolation for all relevant agents still locked
        if self.in_isolation and (self.astep >= self.env.isolation_end):
            if (self.stage == Stage.SUSCEPTIBLE) or (self.stage == Stage.EXPOSED) or \
                (self.stage == Stage.ASYMPTOMATIC):
                self.isolated = False
                self.in_isolation = False

        # Using the model, determine if a susceptible individual becomes infected due to
        # being elsewhere and returning to the community
        if self.stage == Stage.SUSCEPTIBLE:
            if bernoulli.rvs(self.env.rate_inbound):
                self.stage = Stage.EXPOSED

        if self.stage == Stage.SUSCEPTIBLE:
            # Important: infected people drive the spread, not
            # the number of healthy ones

            # If testing is available and the date is reached, test
            # Testing of a healthy person should maintain them as
            # still susceptible.
            # We take care of testing probability at the top level step
            # routine to avoid this repeated computation
            if not(self.tested or self.tested_traced) and bernoulli.rvs(self.test_chance):
                self.tested = True
            # First opportunity to get infected: contact with others
            # in near proximity
            cellmates = self.get_patch().get_agents()
            infected_contact = False

            # Isolated people should only be contagious if they do not follow proper
            # shelter-at-home measures
            for c in cellmates:
                    if c.is_contagious():
                        c.add_contact_trace(self)
                        if self.isolated and bernoulli.rvs(1 - self.env.prob_isolation_effective):
                            self.isolated_but_inefficient = True
                            infected_contact = True
                            break
                        else:
                            infected_contact = True
                            break        
            
            # Value is computed before infected stage happens
            isolation_private_divider = 1
            isolation_public_divider = 1

            if self.employed:
                if self.isolated:
                    isolation_private_divider = 0.3
                    isolation_public_divider = 0.01


                self.cumul_private_value = self.cumul_private_value + \
                    ((len(cellmates) - 1) * self.env.stage_value_dist[ValueGroup.PRIVATE][Stage.SUSCEPTIBLE])*isolation_private_divider
                self.cumul_public_value = self.cumul_public_value + \
                    ((len(cellmates) - 1) * self.env.stage_value_dist[ValueGroup.PUBLIC][Stage.SUSCEPTIBLE])*isolation_public_divider
            else:
                self.cumul_private_value = self.cumul_private_value + 0
                self.cumul_public_value = self.cumul_public_value - 2*self.env.stage_value_dist[ValueGroup.PUBLIC][Stage.SUSCEPTIBLE]

            if infected_contact:
                if self.isolated:
                    if bernoulli.rvs(self.prob_contagion) and \
                        not(bernoulli.rvs(self.env.prob_isolation_effective)):
                        self.stage = Stage.EXPOSED
                else:
                    if bernoulli.rvs(self.prob_contagion):
                        self.stage = Stage.EXPOSED

            # Second opportunity to get infected: residual droplets in places
            # TODO

            if not(self.isolated):
                self.displace()
        elif self.stage == Stage.EXPOSED:
            # Susceptible patients only move and spread the disease.
            # If the incubation time is reached, it is immediately 
            # considered as detected since it is severe enough.

            # We compute the private value as usual
            cellmates = self.get_patch().get_agents()

            isolation_private_divider = 1
            isolation_public_divider = 1

            if self.employed:
                if self.isolated:
                    isolation_private_divider = 0.3
                    isolation_public_divider = 0.01
                
                self.cumul_private_value = self.cumul_private_value + \
                    ((len(cellmates) - 1) * self.env.stage_value_dist[ValueGroup.PRIVATE][Stage.EXPOSED])*isolation_private_divider
                self.cumul_public_value = self.cumul_public_value + \
                    ((len(cellmates) - 1) * self.env.stage_value_dist[ValueGroup.PUBLIC][Stage.EXPOSED])*isolation_public_divider
            else:
                self.cumul_private_value = self.cumul_private_value + 0
                self.cumul_public_value = self.cumul_public_value - 2*self.env.stage_value_dist[ValueGroup.PUBLIC][Stage.EXPOSED]

            # Assignment is less expensive than comparison
            do_move = True

            # If testing is available and the date is reached, test
            if not(self.tested or self.tested_traced) and bernoulli.rvs(self.test_chance):
                if bernoulli.rvs(self.env.prob_asymptomatic):
                    self.stage = Stage.ASYMPDETECTED
                else:
                    self.stage = Stage.SYMPDETECTED
                    do_move = False
                
                self.tested = True
            else:
                if self.curr_incubation < self.incubation_time:
                    self.curr_incubation = self.curr_incubation + 1
                else:
                    if bernoulli.rvs(self.env.prob_asymptomatic):
                        self.stage = Stage.ASYMPTOMATIC
                    else:
                        self.stage = Stage.SYMPDETECTED
                        do_move = False

            # Now, attempt to move
            if do_move and not(self.isolated):
                self.displace()
            
            # Perform the move once the condition has been determined
        elif self.stage == Stage.ASYMPTOMATIC:
            # Asymptomayic patients only roam around, spreading the
            # disease, ASYMPDETECTEDimmune system
            cellmates = self.get_patch().get_agents()

            isolation_private_divider = 1
            isolation_public_divider = 1

            if self.employed:
                if self.isolated:
                    isolation_private_divider = 0.3
                    isolation_public_divider = 0.01
                
                    self.cumul_private_value = self.cumul_private_value + \
                        ((len(cellmates) - 1) * self.env.stage_value_dist[ValueGroup.PRIVATE][Stage.ASYMPTOMATIC])*isolation_private_divider
                    self.cumul_public_value = self.cumul_public_value + \
                        ((len(cellmates) - 1) * self.env.stage_value_dist[ValueGroup.PUBLIC][Stage.ASYMPTOMATIC])*isolation_public_divider
                else:
                    self.cumul_private_value = self.cumul_private_value + 0
                    self.cumul_public_value = self.cumul_public_value - 2*self.env.stage_value_dist[ValueGroup.PUBLIC][Stage.ASYMPTOMATIC]

            if not(self.tested or self.tested_traced) and bernoulli.rvs(self.test_chance):
                self.stage = Stage.ASYMPDETECTED
                self.tested = True
            else:
                if self.curr_recovery >= self.recovery_time:
                    self.stage = Stage.RECOVERED
                    
                if not(self.isolated):
                    self.displace()
                    
        elif self.stage == Stage.SYMPDETECTED:
            # Once a symptomatic patient has been detected, it does not move and starts
            # the road to severity, recovery or death. We assume that, by reaching a health
            # unit, they are tested as positive.
            self.isolated = True
            self.tested = True

            # Contact tracing logic: use a negative number to indicate trace exhaustion
            if self.env.tracing_now and self.tracing_counter >= 0:
                # Test only when the count down has been reached
                if self.tracing_counter == self.tracing_delay:
                    for t in self.contacts:
                        t.test_contact_trace()

                    self.tracing_counter = -1
                else:
                    self.tracing_counter = self.tracing_counter + 1
            
            self.cumul_private_value = self.cumul_private_value + \
                self.env.stage_value_dist[ValueGroup.PRIVATE][Stage.SYMPDETECTED]
            self.cumul_public_value = self.cumul_public_value + \
                self.env.stage_value_dist[ValueGroup.PUBLIC][Stage.SYMPDETECTED]

            if self.curr_incubation + self.curr_recovery < self.incubation_time + self.recovery_time:
                self.curr_recovery = self.curr_recovery + 1

                if bernoulli.rvs(self.severity_value):
                    self.stage = Stage.SEVERE
            else:
                self.stage = Stage.RECOVERED
        elif self.stage == Stage.ASYMPDETECTED:
            self.isolated = True

            # Contact tracing logic: use a negative number to indicate trace exhaustion
            if self.env.tracing_now and self.tracing_counter >= 0:
                # Test only when the count down has been reached
                if self.tracing_counter == self.tracing_delay:
                    for t in self.contacts:
                        t.test_contact_trace()

                    self.tracing_counter = -1
                else:
                    self.tracing_counter = self.tracing_counter + 1

            self.cumul_private_value = self.cumul_private_value + \
                self.env.stage_value_dist[ValueGroup.PRIVATE][Stage.ASYMPDETECTED]
            self.cumul_public_value = self.cumul_public_value + \
                self.env.stage_value_dist[ValueGroup.PUBLIC][Stage.ASYMPDETECTED]

            # The road of an asymptomatic patients is similar without the prospect of death
            if self.curr_incubation + self.curr_recovery < self.incubation_time + self.recovery_time:
               self.curr_recovery = self.curr_recovery + 1
            else:
                self.stage = Stage.RECOVERED
        elif self.stage == Stage.SEVERE:            
            self.cumul_private_value = self.cumul_private_value + \
                self.env.stage_value_dist[ValueGroup.PRIVATE][Stage.SEVERE]
            self.cumul_public_value = self.cumul_public_value + \
                self.env.stage_value_dist[ValueGroup.PUBLIC][Stage.SEVERE]

            # Severe patients are in ICU facilities
            if self.curr_recovery < self.recovery_time:
                # Not recovered yet, may pass away depending on prob.
                if bernoulli.rvs(self.mortality_value):
                    self.stage = Stage.DECEASED
                # If hospital beds are saturated, mortality jumps by a factor of 5x
                #elif self.env.max_beds_available < compute_severe_n(self.env):
                #    if bernoulli.rvs(1.2*self.mortality_value):
                #        self.stage = Stage.DECEASED
                else:
                    self.curr_recovery = self.curr_recovery + 1
            else:
                self.stage = Stage.RECOVERED
        elif self.stage == Stage.RECOVERED:
            cellmates = self.get_patch().get_agents()
            
            if self.employed:
                isolation_private_divider = 1
                isolation_public_divider = 1

                if self.isolated:
                    isolation_private_divider = 0.3
                    isolation_public_divider = 0.01

                self.cumul_private_value = self.cumul_private_value + \
                    ((len(cellmates) - 1) * self.env.stage_value_dist[ValueGroup.PRIVATE][Stage.RECOVERED])*isolation_private_divider
                self.cumul_public_value = self.cumul_public_value + \
                    ((len(cellmates) - 1) * self.env.stage_value_dist[ValueGroup.PUBLIC][Stage.RECOVERED])*isolation_public_divider
            else:
                self.cumul_private_value = self.cumul_private_value + 0
                self.cumul_public_value = self.cumul_public_value - 2*self.env.stage_value_dist[ValueGroup.PUBLIC][Stage.RECOVERED]

            # A recovered agent can now move freely within the grid again
            self.curr_recovery = 0
            self.isolated = False
            self.isolated_but_inefficient = False
            self.displace()
        elif self.stage == Stage.DECEASED:
            self.cumul_private_value = self.cumul_private_value + \
                self.env.stage_value_dist[ValueGroup.PRIVATE][Stage.DECEASED]
            self.cumul_public_value = self.cumul_public_value + \
                self.env.stage_value_dist[ValueGroup.PUBLIC][Stage.DECEASED]
        else:
            # If we are here, there is a problem 
            sys.exit("Unknown stage: aborting.")

        self.astep = self.astep + 1

    def displace(self):
        # If dwelling has not been exhausted, do not move
        if self.curr_dwelling > 0:
            self.curr_dwelling = self.curr_dwelling - 1

        # If dwelling has been exhausted, move and replenish the dwell
        else:
            possible_steps = self.get_patch().neighbors
            new_position = random.choice(possible_steps)

            self.move(new_position,True)
            self.curr_dwelling = poisson.rvs(self.env.avg_dwell)

def compute_susceptible(model):
    return count_type(model, Stage.SUSCEPTIBLE)/model.num_agents

def compute_incubating(model):
    return count_type(model, Stage.EXPOSED)/model.num_agents

def compute_asymptomatic(model):
    return count_type(model, Stage.ASYMPTOMATIC)/model.num_agents

def compute_symptdetected(model):
    return count_type(model, Stage.SYMPDETECTED)/model.num_agents

def compute_severe_n(model):
    return count_type(model, Stage.SEVERE)

def compute_asymptdetected(model):
    return count_type(model, Stage.ASYMPDETECTED)/model.num_agents

def compute_severe(model):
    return count_type(model, Stage.SEVERE)/model.num_agents

def compute_recovered(model):
    return count_type(model, Stage.RECOVERED)/model.num_agents

def compute_deceased(model):
    return count_type(model, Stage.DECEASED)/model.num_agents

def count_type(model, stage):
    count = 0

    for agent in model.agents:
        if agent.stage == stage:
            count = count + 1

    return count

def compute_isolated(model):
    count = 0

    for agent in model.agents:
        if agent.isolated:
            count = count + 1

    return count/model.num_agents

def compute_employed(model):
    count = 0

    for agent in model.agents:
        if agent.employed:
            count = count + 1

    return count/model.num_agents

def compute_unemployed(model):
    count = 0

    for agent in model.agents:
        if not(agent.employed):
            count = count + 1

    return count/model.num_agents

def compute_contacts(model):
    count = 0

    for agent in model.agents:
        count = count + agent.interactants()

    return count/len(model.agents)

def compute_stepno(model):
    return model.stepno

def compute_cumul_private_value(model):
    value = 0

    for agent in model.agents:
        value = value + agent.cumul_private_value

    return np.sign(value)*np.power(np.abs(value), model.alpha_private)/model.num_agents

def compute_cumul_public_value(model):
    value = 0

    for agent in model.agents:
        value = value + agent.cumul_public_value

    return np.sign(value)*np.power(np.abs(value), model.alpha_public)/model.num_agents

def compute_cumul_testing_cost(model):
    tested = 0

    for agent in model.agents:
        if agent.tested:
            tested = tested + 1

    return tested * model.test_cost/model.num_agents

def compute_tested(model):
    tested = 0

    for agent in model.agents:
        if agent.tested:
            tested = tested + 1

    return tested

def compute_traced(model):
    tested = 0

    for agent in model.agents:
        if agent.tested_traced:
            tested = tested + 1

    return tested


def compute_eff_reprod_number(model):
    prob_contagion = 0.0
    
    # Adding logic to better compute R(t)
    exposed = 0.0
    asymptomatics = 0.0
    symptomatics = 0.0
    
    exp_time = 0.0
    asympt_time = 0.0
    sympt_time = 0.0

    for agent in model.agents:
        if agent.stage == Stage.EXPOSED:
            exposed = exposed + 1
            exp_time = exp_time + agent.incubation_time
            prob_contagion = agent.prob_contagion
        elif agent.stage == Stage.SYMPDETECTED:
            # NOTE: this part needs to be adapted to model hospital transmission in further detail
            symptomatics = symptomatics + 1
            sympt_time = sympt_time + agent.incubation_time
            prob_contagion = agent.prob_contagion
        elif agent.stage == Stage.ASYMPTOMATIC:
            asymptomatics = asymptomatics + 1
            asympt_time = asympt_time + agent.incubation_time + agent.recovery_time
            prob_contagion = agent.prob_contagion
        else:
            continue

    total = exposed + symptomatics + asymptomatics

    # Compute partial contributions
    times = []

    if exposed != 0:
        times.append(exp_time/exposed)

    if symptomatics != 0:
        times.append(sympt_time/symptomatics)

    if asymptomatics != 0:
        # print(symptomatics)
        times.append(asympt_time/asymptomatics)

    if total != 0:
        infectious_period = np.mean(times)
    else:
        infectious_period = 0

    avg_contacts = compute_contacts(model)
    return model.kmob * model.repscaling * prob_contagion * avg_contacts * infectious_period

def compute_num_agents(model):
    return model.num_agents

class CovidModel(Env):
    """ A model to describe parameters relevant to COVID-19"""
    def __init__(self, steps, num_agents, width, height, kmob, repscaling, rate_inbound, age_mortality, 
                 sex_mortality, age_distribution, sex_distribution, prop_initial_infected, 
                 proportion_asymptomatic, proportion_severe, avg_incubation_time, avg_recovery_time, prob_contagion,
                 proportion_isolated, day_start_isolation, days_isolation_lasts, after_isolation, prob_isolation_effective, social_distance,
                 day_distancing_start, days_distancing_lasts, proportion_detected, day_testing_start, days_testing_lasts, 
                 new_agent_proportion, new_agent_start, new_agent_lasts, new_agent_age_mean, new_agent_prop_infected,
                 day_tracing_start, days_tracing_lasts, stage_value_matrix, test_cost, alpha_private, alpha_public, proportion_beds_pop, dummy=0):
        Env.__init__(self)
        self.steps = steps
        self.max_memory_usages = []
        self.data = {'susceptible':[],'symptomatics':[],'exposed':[],'asymptomatics':[]} # SymptQuarantined
        self.patches_repo = []
        self.agents_repo = []
        self.running = True
        self.num_agents = num_agents
        mesh = space.grid2(length=height, width=width, mesh_length=1, share = True)
        self.setup_domain(mesh)
        self.age_mortality = age_mortality
        self.sex_mortality = sex_mortality
        self.age_distribution = age_distribution
        self.sex_distribution = sex_distribution
        self.stage_value_dist = stage_value_matrix
        self.test_cost = test_cost
        self.stepno = 0
        self.alpha_private = alpha_private
        self.alpha_public = alpha_public

        # Number of 15 minute dwelling times per day
        self.dwell_15_day = 96

        # Average dwelling units
        self.avg_dwell = 4

        # The average incubation period is 5 days, which can be changed
        self.avg_incubation = int(round(avg_incubation_time * self.dwell_15_day))

        # Probability of contagion after exposure in the same cell
        # Presupposes a person centered on a 1.8 meter radius square.
        # We use a proxy value to account for social distancing.
        # Representativeness modifies the probability of contagion by the scaling factor
        if repscaling < 2:
            self.repscaling = 1
        else:
            self.repscaling = (np.log(repscaling)/np.log(1.96587))
        
        self.prob_contagion_base = prob_contagion / self.repscaling

        # Mobility constant for geographic rescaling
        self.kmob = kmob

        # Proportion of daily incoming infected people from other places
        self.rate_inbound = rate_inbound/self.dwell_15_day

        # Probability of contagion due to residual droplets: TODO
        self.prob_contagion_places = 0.001

        # Probability of being asymptomatic, contagious
        # and only detectable by testing
        self.prob_asymptomatic = proportion_asymptomatic

        # Average recovery time
        self.avg_recovery = avg_recovery_time * self.dwell_15_day

        # Proportion of detection. We use the rate as reference and
        # activate testing at the rate and specified dates
        self.testing_rate = proportion_detected/(days_testing_lasts  * self.dwell_15_day)
        self.testing_start = day_testing_start* self.dwell_15_day
        self.testing_end = self.testing_start + days_testing_lasts*self.dwell_15_day

        # We need an additional variable to activate and inactivate automatic contact tracing
        self.tracing_start = day_tracing_start* self.dwell_15_day
        self.tracing_end = self.tracing_start + days_tracing_lasts*self.dwell_15_day
        self.tracing_now = False

        # Same for isolation rate
        self.isolation_rate = proportion_isolated
        self.isolation_start = day_start_isolation*self.dwell_15_day
        self.isolation_end = self.isolation_start + days_isolation_lasts*self.dwell_15_day
        self.after_isolation = after_isolation
        self.prob_isolation_effective = prob_isolation_effective

        # Same for social distancing
        self.distancing = social_distance
        self.distancing_start = day_distancing_start*self.dwell_15_day
        self.distancing_end = self.distancing_start + days_distancing_lasts*self.dwell_15_day

        # Introduction of new agents after a specific time
        self.new_agent_num = int(new_agent_proportion * self.num_agents)
        self.new_agent_start = new_agent_start*self.dwell_15_day
        self.new_agent_end = self.new_agent_start + new_agent_lasts*self.dwell_15_day
        self.new_agent_age_mean = new_agent_age_mean
        self.new_agent_prop_infected = new_agent_prop_infected

        # Closing of various businesses
        # TODO: at the moment, we assume that closing businesses decreases the dwell time.
        # A more proper implementation would a) use a power law distribution for dwell times
        # and b) assign a background of dwell times first, modifying them upwards later
        # for all cells.
        # Alternatively, shutting restaurants corresponds to 15% of interactions in an active day, and bars to a 7%
        # of those interactions


        # Now, a neat python trick: generate the spacing of entries and then build a map
        times_list = list(np.linspace(self.new_agent_start, self.new_agent_end, self.new_agent_num, dtype=int))
        self.new_agent_time_map = {x:times_list.count(x) for x in times_list}

        # Probability of severity
        self.prob_severe = proportion_severe

        # Number of beds where saturation limit occurs
        self.max_beds_available = self.num_agents * proportion_beds_pop

        # Create agents


        for ag in self.age_distribution:
            for sg in self.sex_distribution:
                r = self.age_distribution[ag]*self.sex_distribution[sg]
                num_agents = int(round(self.num_agents*r))
                mort = self.age_mortality[ag]*self.sex_mortality[sg]
                for k in range(num_agents):
                    a =self.generate_agent("Person", ag, sg, mort)
                    dest = random.choice(self.patches)
                    self.place_agent(dest,a,True)
        
        # self.datacollector = DataCollector(
        #     model_reporters = {
        #         "Step": compute_stepno,
        #         "N": compute_num_agents,
        #         "Susceptible": compute_susceptible,
        #         "Exposed": compute_incubating,
        #         "Asymptomatic": compute_asymptomatic,
        #         "SymptQuarantined": compute_symptdetected,
        #         "AsymptQuarantined": compute_asymptdetected,
        #         "Severe": compute_severe,
        #         "Recovered": compute_recovered,
        #         "Deceased": compute_deceased,
        #         "Isolated": compute_isolated,
        #         "CumulPrivValue": compute_cumul_private_value,
        #         "CumulPublValue": compute_cumul_public_value,
        #         "CumulTestCost": compute_cumul_testing_cost,
        #         "Rt": compute_eff_reprod_number,
        #         "Employed": compute_employed,
        #         "Unemployed": compute_unemployed,
        #         "Tested": compute_tested,
        #         "Traced": compute_traced
        #     }
        # )

        # Final step: infect an initial proportion of random agents
        num_init = int(self.num_agents * prop_initial_infected)
        
        for a in self.agents:
            if num_init < 0:
                break
            else:
                a.stage = Stage.EXPOSED
                num_init = num_init - 1
    def generate_agent(self,agent_name,ag, sg, mort):
        """
        Extension of the original function to create agents
        """
        agent_obj = CovidAgent(self,agent_name, ag, sg, mort)
        self.agents_repo.append(agent_obj)
        self.agents.append(agent_obj)
        return agent_obj
    def generate_patch(self,mesh_item):
        """
        Extension of the original function to create pacthes
        """
        patch_obj = Patch(self,mesh_item)
        self.patches.append(patch_obj);
        self.patches_repo.append(patch_obj)
        return patch_obj
    def step(self):
        # self.datacollector.collect(self)
        
        if self.stepno % self.dwell_15_day == 0:
            print(f'Simulating day {self.stepno // self.dwell_15_day}')

        # Activate contact tracing only if necessary and turn it off correspondingly at the end
        if not(self.tracing_now) and (self.stepno >= self.tracing_start):
            self.tracing_now = True
        
        if self.tracing_now and (self.stepno > self.tracing_end):
            self.tracing_now = False
        self.stepno = self.stepno + 1
        
        # If new agents enter the population, create them
        if (self.stepno >= self.new_agent_start) and (self.stepno < self.new_agent_end):
            # Check if the current step is in the new-agent time map
            if self.stepno in self.new_agent_time_map.keys():
                # We repeat the following procedure as many times as the value stored in the map

                for _ in range(0, self.new_agent_time_map[self.stepno]):
                    # Generate an age group at random using a Poisson distribution centered at the mean
                    # age for the incoming population
                    in_range = False
                    arange = 0

                    while not(in_range):
                        arange = poisson.rvs(self.new_agent_age_mean)
                        if arange in range(0, 9):
                            in_range = True
                    
                    ag = AgeGroup(arange)
                    sg = random.choice(list(SexGroup))
                    mort = self.age_mortality[ag]*self.sex_mortality[sg]
                    a = self.generate_agent('Person', ag, sg, mort)
                    
                    # Some will be infected
                    if bernoulli.rvs(self.new_agent_prop_infected):
                        a.stage = Stage.EXPOSED

                    dest = random.choice(self.patches)
                    self.place_agent(dest,a,True)
                    self.num_agents = self.num_agents + 1
        for agent in self.agents:
            agent.step()
        self.calculate_memor_usage()
        self.output()
    def output(self):
        data_scheme = {'susceptible':0,'symptomatics':0,'exposed':0,'asymptomatics':0}
        for agent in self.agents:
            if agent.stage == Stage.SUSCEPTIBLE:
                data_scheme['susceptible']+=1
            elif agent.stage == Stage.SYMPDETECTED:
                data_scheme['symptomatics']+=1
            elif agent.stage == Stage.EXPOSED:
                data_scheme['exposed'] +=1
            elif agent.stage == Stage.ASYMPTOMATIC:
                data_scheme['asymptomatics']+=1
        for key,value in data_scheme.items():
            self.data[key].append(value/len(self.agents))
    def episode(self):
        for i in range(self.steps):
        # for i in range(2):
            self.step()
        return self.data
    def calculate_memor_usage(self):
        process = psutil.Process(os.getpid())
        self.max_memory_usages.append(process.memory_info().rss/1000000)  # in bytes 
        

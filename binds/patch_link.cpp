#include "patch.cpp"
struct PyPatch : public Patch {
    using Patch::Patch;
    void step() override {
    	PYBIND11_OVERLOAD(
    		void,
    		Patch,
    		step
    		);
    }
};


void link_patch(py::module &m){
	py::class_<Patch,PyPatch,std::shared_ptr<Patch>>(m,"Patch",py::dynamic_attr())
    	.def(py::init<shared_ptr<Env>>())
    	.def("empty_neighbor", &Patch::empty_neighbor,"Return an empty patch around the patch",
    		py::arg("quiet")=false)
    	.def("find_neighbor_agents",&Patch::find_neighbor_agents,"Returns a vector of agents in one patch neighborhood",
    		py::arg("include_self")=true)
    	.def_readwrite("coords",&Patch::coords)
    	.def_readwrite("agent",&Patch::agent)
    	.def_readwrite("empty",&Patch::empty)
    	.def_readwrite("disappear",&Patch::disappear)
    	.def_readwrite("data",&Patch::data)
    	.def_readwrite("neighbors",&Patch::neighbors);
    	
}
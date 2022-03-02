# simple bn for bayescard
import magics.magics
import matplotlib.pyplot as plt
import numpy as np
from collections import Counter

%%sppl bn1
dAge   ~= choice({"0":0.179, "1":0.165, "2":0.151,"3":0.135,"4":0.131,"5":0.127,"6":0.099,"7":0.013})
if (dAge == "0"):
    dIncome5 ~= choice({"0":1.0,"1":0.0})
elif (dAge == "1"):
    dIncome5 ~= choice({"0":0.982,"1":0.018})
elif (dAge == "2"):
    dIncome5 ~= choice({"0":0.988,"1":0.012})
elif (dAge == "3"):
    dIncome5 ~= choice({"0":0.853,"1":0.147})
elif (dAge == "4"):
    dIncome5 ~= choice({"0":0.163,"1":0.837})
elif (dAge == "5"):
    dIncome5 ~= choice({"0":0.975,"1":0.025})
elif (dAge == "6"):
    dIncome5 ~= choice({"0":0.980,"1":0.020})
else:
    dIncome5 ~= choice({"0":1.0,"1":0.0})

%sppl_to_graph bn1
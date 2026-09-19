"""One predeclared mild recency contrast; every admitted year retains weight."""
import numpy as np

def year_probabilities(years,half_life):
    years=np.asarray(years)
    assert half_life>0 and len(years)>0
    p=2.**((years-years.max())/half_life)
    return p/p.sum()

def draw(data,rng,half_life=None,dates=16,stocks=16):
    if half_life is None:return data.draw(rng,dates,stocks)
    p=year_probabilities(data.years,half_life)
    return np.concatenate([rng.choice((g:=data.groups[int(rng.choice(data.years,p=p))])[int(rng.integers(len(g)))],stocks,replace=True) for _ in range(dates)])

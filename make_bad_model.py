import joblib, numpy as np
from sklearn.dummy import DummyClassifier
X = np.random.rand(20, 6)
y = np.array([0,1]*10)
bad = DummyClassifier(strategy='constant', constant=1)
bad.fit(X, y)
joblib.dump(bad, 'model_bad.joblib')
print('done')

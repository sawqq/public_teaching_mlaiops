from google.cloud import aiplatform
from src import config

cfg = config.load()
aiplatform.init(project=cfg.project_id, location=cfg.region)

model = aiplatform.Model.upload(
    display_name='itcs355-canary-bad',
    serving_container_image_uri='asia-southeast1-docker.pkg.dev/itcs355-6688101/itcs355/itcs355-serve@sha256:b3ec9e5b469c496506fbebf832ab84d15063d576409eaa26ab3c8a2b365b292f',
    serving_container_predict_route='/predict',
    serving_container_health_route='/ready',
    serving_container_ports=[8080],
    serving_container_environment_variables={'MODEL_PATH': '/app/model.joblib', 'MODEL_VERSION': 'v1-bad'},
)

ep = aiplatform.Endpoint('3337530162718703616')
model.deploy(
    endpoint=ep,
    deployed_model_display_name='canary-v1-bad',
    machine_type='n1-standard-2',
    min_replica_count=1,
    max_replica_count=1,
    traffic_percentage=10,
)
print('canary model resource name:', model.resource_name)
print('canary deployed OK')

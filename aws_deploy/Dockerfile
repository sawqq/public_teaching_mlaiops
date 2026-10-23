
FROM itcs355-serve:aws-swap
COPY --chown=runner:runner aws_deploy/model.joblib /app/model.joblib
ENV MODEL_PATH=/app/model.joblib MODEL_VERSION=aws-swap

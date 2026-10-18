"""Check the alternate Docker API with project credentials; never print secrets."""

from maintenance_policy import cli_gate, maintenance_action
cli_gate(__file__, __name__)

@maintenance_action('probe.mock')
def main():
    import time
    from uuid import uuid4
    import httpx
    from app.core.config import Settings

    settings=Settings()
    headers={'Authorization':'Bearer '+settings.admin_token.get_secret_value()}
    with httpx.Client(base_url='http://127.0.0.1:18101',headers=headers,timeout=5) as client:
        assert client.get('/health/ready').status_code==200
        response=client.post('/api/v1/tasks',headers={'Idempotency-Key':str(uuid4())},json={'goal':'P2 Docker worker verification','execution_mode':'mock','require_approval':False})
        assert response.status_code in {200,202}
        task_id=response.json()['data']['task_id']
        for _ in range(100):
            task=client.get('/api/v1/tasks/'+task_id).json()['data']
            if task['status'] in {'succeeded','failed','limit_exceeded','timed_out','cancelled'}: break
            time.sleep(0.1)
        assert task['status']=='succeeded'
        assert len(task['calls'])==4 and all(row['is_mock'] for row in task['calls'])
    print('PASS: Docker API, independent Docker worker, PostgreSQL and Redis; 4 Mock roles completed')


if __name__ == "__main__":
    main()

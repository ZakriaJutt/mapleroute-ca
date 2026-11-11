"""Synthetic fixtures shared by the tests. No real account IDs, keys or prompts."""

from __future__ import annotations

import io
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from console.app import ConsoleServices, Principal
from console.app import create_app as create_console
from console.auth import SignInLimits
from core import keys, policy_store
from core.alerts import FakePager
from core.crypto import FakeKeyService, encrypt_secret
from core.fakes import (
    FakeAwsAccount,
    FakeAwsReader,
    FakeAwsSessions,
    FakeAzureDeployment,
    FakeAzureReader,
    FakeInference,
    canadian_profile,
)
from core.mail import Mailer, MemoryMailer
from core.models import ApiKey, Binding, ConnectionSecret, Membership, Project, ProviderConnection, Tenant, UserAccount
from core.providers import DeploymentAnswer, FoundationModelAnswer
from core.secretvalue import SecretValue
from core.storage import MemoryObjectStore, ObjectStore
from core.verification import Applied
from gateway.app import GatewayServices, RateLimiter
from gateway.app import create_app as create_gateway
from worker.jobs import WorkerServices, verify_binding


def role_url(role: str) -> str:
    return f"postgresql+psycopg://mapleroute_{role}@localhost:5432/mapleroute_test"


GATEWAY_URL, CONSOLE_URL, WORKER_URL, OPERATOR_URL = (role_url(r) for r in ("gateway", "console", "worker", "operator"))
# The internet-facing process role. (Was the single B1 role `mapleroute_app`, retired in 0003.)
APP_URL = GATEWAY_URL
OWNER_URL = "postgresql+psycopg://zakria@localhost:5432/mapleroute_test"
FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "allowlist-2026.11.10-1.json"

HAIKU = "aws:ca-central-1:geo_ca:ca.anthropic.claude-haiku-5-5"
TITAN = "aws:ca-central-1:in_region:amazon.titan-embed-text-v2:0"
GPT4O = "azure:canadaeast:Standard:gpt-4o:2024-11-20"


def fixture_routes() -> list[dict[str, Any]]:
    return list(json.loads(FIXTURE.read_text())["routes"])


@dataclass
class T:
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    key: str
    key_id: uuid.UUID
    user_id: uuid.UUID


@dataclass
class World:
    owner: sessionmaker[Session]
    app: sessionmaker[Session]  # worker role (verification, jobs)
    clock: Any
    logs: io.StringIO
    gw: sessionmaker[Session]
    con: sessionmaker[Session]
    ops: sessionmaker[Session]
    inference: FakeInference = field(default_factory=FakeInference)
    aws_sessions: FakeAwsSessions = field(default_factory=FakeAwsSessions)
    aws_reader: FakeAwsReader = field(default_factory=FakeAwsReader)
    azure_reader: FakeAzureReader = field(default_factory=FakeAzureReader)
    key_service: FakeKeyService = field(default_factory=FakeKeyService)
    pager: FakePager = field(default_factory=FakePager)
    operator_id: uuid.UUID | None = None
    rate_limit: int = 10_000

    # ------------------------------------------------------------- allow-list
    def operator(self) -> uuid.UUID:
        if self.operator_id is None:
            with self.owner.begin() as s:
                u = UserAccount(idp="entra", idp_subject=f"op-{uuid.uuid4()}", email="op@example.test",
                                display_name="Operator", is_operator=True)
                s.add(u)
                s.flush()
                self.operator_id = u.id
        return self.operator_id

    def activate(self, routes: list[dict[str, Any]] | None = None, version: str = "2026.11.10-1") -> None:
        op = self.operator()
        with self.ops.begin() as s:
            policy_store.publish_draft(s, version, routes if routes is not None else fixture_routes(), op)
        with self.ops.begin() as s:
            policy_store.approve(s, version, op, self.clock())

    # ------------------------------------------------------------- tenants
    def tenant(self, name: str) -> T:
        new = keys.generate()
        with self.owner.begin() as s:
            t = Tenant(legal_name=f"{name} Software Inc. (synthetic)")
            s.add(t)
            s.flush()
            u = UserAccount(idp="google", idp_subject=f"{name}-{uuid.uuid4()}", email=f"eng@{name}.example.test",
                            display_name=f"{name} engineer")
            s.add(u)
            s.flush()
            s.add(Membership(tenant_id=t.id, user_id=u.id, role="owner"))
            p = Project(tenant_id=t.id, name=f"{name}-project")
            s.add(p)
            s.flush()
            k = ApiKey(tenant_id=t.id, project_id=p.id, key_hash=new.key_hash, prefix=new.prefix,
                       last_four=new.last_four)
            s.add(k)
            s.flush()
            return T(t.id, p.id, new.plaintext, k.id, u.id)

    def aws_conn(self, t: T, region: str = "ca-central-1", account: FakeAwsAccount | None = None) -> uuid.UUID:
        role = f"arn:aws:iam::000000000000:role/mapleroute-{uuid.uuid4().hex[:8]}"
        acct = account or FakeAwsAccount(
            profiles={"ca.anthropic.claude-haiku-5-5": canadian_profile("ca.anthropic.claude-haiku-5-5")},
            models={"amazon.titan-embed-text-v2:0": FoundationModelAnswer("amazon.titan-embed-text-v2:0", True, True)},
        )
        self.aws_reader.accounts[role] = acct
        with self.owner.begin() as s:
            c = ProviderConnection(tenant_id=t.tenant_id, project_id=t.project_id, provider="aws",
                                   account_ref=f"0000{uuid.uuid4().hex[:8]}", source_region=region, role_arn=role,
                                   external_id="ext-synthetic", state="connected")
            s.add(c)
            s.flush()
            return c.id

    def azure_conn(self, t: T, host: str, secret: str = "synthetic-azure-key",  # noqa: S107 - synthetic
                   region: str = "canadaeast") -> uuid.UUID:
        with self.owner.begin() as s:
            c = ProviderConnection(tenant_id=t.tenant_id, project_id=t.project_id, provider="azure",
                                   account_ref=f"/subscriptions/synthetic/{host}", source_region=region,
                                   endpoint_host=host, resource_group="rg-synthetic", state="connected")
            s.add(c)
            s.flush()
            env = encrypt_secret(self.key_service, t.tenant_id, c.id, SecretValue(secret))
            s.add(ConnectionSecret(connection_id=c.id, tenant_id=t.tenant_id, ciphertext=env.ciphertext,
                                   wrapped_data_key=env.wrapped_data_key, kms_key_arn=env.kms_key_arn))
            return c.id

    def azure_deployment(self, host: str, name: str, sku: str = "Standard", model: str = "gpt-4o",
                         version: str = "2024-11-20", location: str = "canadaeast") -> FakeAzureDeployment:
        created = self.clock().replace(hour=0)
        dep = FakeAzureDeployment(DeploymentAnswer(location, sku, model, version, created, created))
        self.azure_reader.deployments[(host, name)] = dep
        return dep

    def bind(self, t: T, conn: uuid.UUID, route_id: str, alias: str, deployment_name: str | None = None) -> uuid.UUID:
        with self.owner.begin() as s:
            b = Binding(tenant_id=t.tenant_id, project_id=t.project_id, connection_id=conn, route_id=route_id,
                        alias=alias, deployment_name=deployment_name)
            s.add(b)
            s.flush()
            return b.id

    # ------------------------------------------------------------- processes
    def worker_services(self) -> WorkerServices:
        return WorkerServices(self.aws_reader, self.azure_reader, self.key_service, self.pager)

    def verify(self, t: T, binding_id: uuid.UUID) -> Applied:
        with self.app.begin() as s:
            return verify_binding(s, self.worker_services(), t.tenant_id, binding_id, self.clock())

    def gateway(self, factory: sessionmaker[Session] | None = None) -> TestClient:
        services = GatewayServices(
            factory=factory or self.gw, clients={"aws": self.inference, "azure": self.inference},
            aws_sessions=self.aws_sessions, key_service=self.key_service, limiter=RateLimiter(self.rate_limit),
        )
        return TestClient(create_gateway(services))

    def console(self, principal: Principal | None) -> TestClient:
        return TestClient(create_console(ConsoleServices(self.con, self.key_service, lambda request: principal,
                                                         ops_factory=self.ops)))

    @staticmethod
    def chat(client: TestClient, key: str, alias: str, **extra: Any) -> Any:
        body = {"model": alias, "messages": [{"role": "user", "content": "synthetic question"}], **extra}
        return client.post("/v1/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"})

    def session_console(self, mailer: Mailer | None = None, store: ObjectStore | None = None,
                        limits: SignInLimits | None = None) -> TestClient:
        """The console with the real session authenticator (B2). HTTPS base URL so the Secure cookie is sent."""
        services = ConsoleServices(self.con, self.key_service, None, ops_factory=self.ops,
                                   mailer=mailer or MemoryMailer(), store=store or MemoryObjectStore(),
                                   public_base_url=CONSOLE_PUBLIC_URL, limits=limits or SignInLimits())
        return TestClient(create_console(services), base_url="https://testserver")


CONSOLE_PUBLIC_URL = "https://console.mapleroute.localhost"

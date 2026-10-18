"""Frozen pre-migration schema; never change this historical snapshot."""

import sqlalchemy as sa


def metadata(*, deliveries: bool = False) -> sa.MetaData:
    """Reconstruct the two supported unversioned legacy schema shapes."""
    schema = sa.MetaData()
    sa.Table(
        "jobs",
        schema,
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("kind", sa.String(20), primary_key=False, nullable=False),
        sa.Column("payload", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("status", sa.String(20), primary_key=False, nullable=False),
        sa.Column("attempts", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("max_attempts", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("worker_id", sa.String(80), primary_key=False, nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), primary_key=False, nullable=True),
        sa.Column("run_after", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.Column("last_error", sa.Text(), primary_key=False, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )
    sa.Index(
        "ix_jobs_claim",
        schema.tables["jobs"].c["status"],
        schema.tables["jobs"].c["run_after"],
        unique=False,
    )
    sa.Table(
        "users",
        schema,
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("name", sa.String(200), primary_key=False, nullable=False),
        sa.Column("token_hash", sa.String(64), primary_key=False, nullable=True),
        sa.Column("is_admin", sa.Boolean(), primary_key=False, nullable=False),
        sa.Column("github_login", sa.String(200), primary_key=False, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.UniqueConstraint("token_hash", name=None),
    )
    sa.Table(
        "github_installations",
        schema,
        sa.Column("installation_id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.String(40),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("account", sa.String(200), primary_key=False, nullable=True),
    )
    sa.Table(
        "repositories",
        schema,
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column(
            "owner_id",
            sa.String(40),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("full_name", sa.String(300), primary_key=False, nullable=False),
        sa.Column("kind", sa.String(20), primary_key=False, nullable=False),
        sa.Column("local_path", sa.Text(), primary_key=False, nullable=True),
        sa.Column("github_installation_id", sa.Integer(), primary_key=False, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.UniqueConstraint("owner_id", "full_name", name="uq_repo_owner_name"),
    )
    sa.Index("ix_repositories_owner_id", schema.tables["repositories"].c["owner_id"], unique=False)
    sa.Table(
        "pull_requests",
        schema,
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column(
            "repository_id",
            sa.String(40),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("title", sa.Text(), primary_key=False, nullable=False),
        sa.Column("author", sa.String(200), primary_key=False, nullable=True),
        sa.Column("url", sa.Text(), primary_key=False, nullable=True),
        sa.Column("head_sha", sa.String(64), primary_key=False, nullable=True),
        sa.Column("base_sha", sa.String(64), primary_key=False, nullable=True),
        sa.Column("state", sa.String(20), primary_key=False, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.UniqueConstraint("repository_id", "number", name="uq_pr_repo_number"),
    )
    sa.Index(
        "ix_pull_requests_repository_id",
        schema.tables["pull_requests"].c["repository_id"],
        unique=False,
    )
    sa.Table(
        "reviews",
        schema,
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column(
            "repository_id",
            sa.String(40),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column(
            "pull_request_id",
            sa.String(40),
            sa.ForeignKey("pull_requests.id", ondelete="SET NULL"),
            primary_key=False,
            nullable=True,
        ),
        sa.Column("status", sa.String(20), primary_key=False, nullable=False),
        sa.Column("source", sa.String(20), primary_key=False, nullable=False),
        sa.Column("title", sa.Text(), primary_key=False, nullable=True),
        sa.Column("base_ref", sa.String(200), primary_key=False, nullable=True),
        sa.Column("head_ref", sa.String(200), primary_key=False, nullable=True),
        sa.Column("risk", sa.String(10), primary_key=False, nullable=True),
        sa.Column("provider", sa.String(40), primary_key=False, nullable=True),
        sa.Column("model", sa.String(100), primary_key=False, nullable=True),
        sa.Column("input_tokens", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("output_tokens", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("request", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("summary", sa.JSON(), primary_key=False, nullable=True),
        sa.Column("stages", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("changeset", sa.JSON(), primary_key=False, nullable=True),
        sa.Column("sources", sa.JSON(), primary_key=False, nullable=True),
        sa.Column("errors", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), primary_key=False, nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), primary_key=False, nullable=True),
        sa.Column("duration_ms", sa.Integer(), primary_key=False, nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), primary_key=False, nullable=True),
    )
    sa.Index("ix_reviews_created_at", schema.tables["reviews"].c["created_at"], unique=False)
    sa.Index("ix_reviews_repository_id", schema.tables["reviews"].c["repository_id"], unique=False)
    sa.Index("ix_reviews_status", schema.tables["reviews"].c["status"], unique=False)
    sa.Table(
        "analysis_runs",
        schema,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "review_id",
            sa.String(40),
            sa.ForeignKey("reviews.id", ondelete="CASCADE"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("tool", sa.String(40), primary_key=False, nullable=False),
        sa.Column("status", sa.String(20), primary_key=False, nullable=False),
        sa.Column("duration_ms", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("findings", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("detail", sa.Text(), primary_key=False, nullable=False),
    )
    sa.Index(
        "ix_analysis_runs_review_id", schema.tables["analysis_runs"].c["review_id"], unique=False
    )
    sa.Table(
        "code_graph_snapshots",
        schema,
        sa.Column(
            "review_id",
            sa.String(40),
            sa.ForeignKey("reviews.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("graph", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )
    sa.Table(
        "findings",
        schema,
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column(
            "review_id",
            sa.String(40),
            sa.ForeignKey("reviews.id", ondelete="CASCADE"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("rank", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("fingerprint", sa.String(32), primary_key=False, nullable=False),
        sa.Column("category", sa.String(20), primary_key=False, nullable=False),
        sa.Column("severity", sa.String(10), primary_key=False, nullable=False),
        sa.Column("confidence", sa.Float(), primary_key=False, nullable=False),
        sa.Column("title", sa.Text(), primary_key=False, nullable=False),
        sa.Column("file", sa.Text(), primary_key=False, nullable=False),
        sa.Column("line_start", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("line_end", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("source", sa.String(20), primary_key=False, nullable=False),
        sa.Column("status", sa.String(20), primary_key=False, nullable=False),
        sa.Column("verification_status", sa.String(20), primary_key=False, nullable=True),
        sa.Column("priority", sa.Float(), primary_key=False, nullable=False),
        sa.Column("suppressed", sa.Boolean(), primary_key=False, nullable=False),
        sa.Column("suppressed_reason", sa.Text(), primary_key=False, nullable=True),
        sa.Column("merged_ids", sa.Text(), primary_key=False, nullable=False),
        sa.Column("data", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )
    sa.Index("ix_findings_fingerprint", schema.tables["findings"].c["fingerprint"], unique=False)
    sa.Index("ix_findings_review_id", schema.tables["findings"].c["review_id"], unique=False)
    sa.Table(
        "finding_events",
        schema,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "finding_id",
            sa.String(40),
            sa.ForeignKey("findings.id", ondelete="CASCADE"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(40), primary_key=False, nullable=True),
        sa.Column("event", sa.String(40), primary_key=False, nullable=False),
        sa.Column("from_status", sa.String(20), primary_key=False, nullable=True),
        sa.Column("to_status", sa.String(20), primary_key=False, nullable=True),
        sa.Column("note", sa.Text(), primary_key=False, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )
    sa.Index(
        "ix_finding_events_finding_id",
        schema.tables["finding_events"].c["finding_id"],
        unique=False,
    )
    sa.Table(
        "fix_attempts",
        schema,
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column(
            "finding_id",
            sa.String(40),
            sa.ForeignKey("findings.id", ondelete="CASCADE"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("status", sa.String(20), primary_key=False, nullable=False),
        sa.Column("summary", sa.Text(), primary_key=False, nullable=True),
        sa.Column("patch", sa.Text(), primary_key=False, nullable=True),
        sa.Column("edits", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("checks", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("original_hashes", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("isolation", sa.String(40), primary_key=False, nullable=True),
        sa.Column("provider", sa.String(40), primary_key=False, nullable=True),
        sa.Column("model", sa.String(100), primary_key=False, nullable=True),
        sa.Column("attempts", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("error", sa.Text(), primary_key=False, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), primary_key=False, nullable=True),
    )
    sa.Index(
        "ix_fix_attempts_finding_id", schema.tables["fix_attempts"].c["finding_id"], unique=False
    )
    if deliveries:
        sa.Table(
            "github_deliveries",
            schema,
            sa.Column("key", sa.String(80), primary_key=True),
            sa.Column(
                "review_id",
                sa.String(40),
                sa.ForeignKey("reviews.id", ondelete="CASCADE"),
                nullable=False,
            ),
        )
    return schema

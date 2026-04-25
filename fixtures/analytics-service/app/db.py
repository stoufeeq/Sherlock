"""
Reads across schemas owned by other services. Changing column names or dropping
tables in those services will break the queries below — this is exactly the kind
of silent coupling Sherlock should surface.
"""

import os

import psycopg

DSN = os.getenv(
    "ANALYTICS_DSN",
    "postgresql://banking:banking@postgres:5432/banking",
)


class _DB:
    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(DSN)

    def daily_volume(self) -> list[dict]:
        sql = """
            SELECT date_trunc('day', t.created_at)::date AS day,
                   t.currency,
                   SUM(t.amount) AS total
            FROM transactions.transactions t
            GROUP BY 1, 2
            ORDER BY 1 DESC, 2
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql)
            return [
                {"day": r[0].isoformat(), "currency": r[1], "total": float(r[2])}
                for r in cur.fetchall()
            ]

    def customer_summary(self, customer_id: str) -> dict:
        sql = """
            SELECT c.id, c.full_name,
                   COUNT(DISTINCT a.id) AS num_accounts,
                   COALESCE(SUM(b.amount), 0) AS total_balance
            FROM customers.customers c
            LEFT JOIN accounts.accounts a ON a.customer_id = c.id
            LEFT JOIN ledger.balances b ON b.account_id = a.id
            WHERE c.id = %s
            GROUP BY c.id, c.full_name
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, (customer_id,))
            row = cur.fetchone()
            if not row:
                return {"customerId": customer_id, "found": False}
            return {
                "customerId": row[0],
                "fullName": row[1],
                "numAccounts": row[2],
                "totalBalance": float(row[3]),
                "found": True,
            }


db = _DB()

import express from 'express';
import { accountClient } from './clients/accountClient.js';
import { transactionClient } from './clients/transactionClient.js';
import { customerClient } from './clients/customerClient.js';

const app = express();
app.use(express.json());

app.get('/health', (_req, res) => res.json({ status: 'ok' }));

app.get('/api/overview/:customerId', async (req, res) => {
  const { customerId } = req.params;
  try {
    const customer = await customerClient.get(customerId);
    const accountId = `acc-${customerId}`;
    const [account, balance] = await Promise.all([
      accountClient.get(accountId),
      accountClient.getBalance(accountId),
    ]);
    res.json({ customer, account, balance });
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

app.post('/api/transactions', async (req, res) => {
  try {
    const tx = await transactionClient.create(req.body);
    res.status(201).json(tx);
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

const port = process.env.PORT || 3000;
app.listen(port, () => console.log(`web-portal-bff listening on ${port}`));

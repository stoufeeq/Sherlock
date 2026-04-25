import express from 'express';
import { accountClient } from './clients/accountClient.js';
import { transactionClient } from './clients/transactionClient.js';
import { notificationClient } from './clients/notificationClient.js';

const app = express();
app.use(express.json());

app.get('/health', (_req, res) => res.json({ status: 'ok' }));

app.get('/mobile/home/:customerId', async (req, res) => {
  const accountId = `acc-${req.params.customerId}`;
  try {
    const [account, balance] = await Promise.all([
      accountClient.get(accountId),
      accountClient.getBalance(accountId),
    ]);
    res.json({ account, balance });
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

app.post('/mobile/transactions', async (req, res) => {
  try {
    const tx = await transactionClient.create(req.body);
    res.status(201).json(tx);
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

app.post('/mobile/notifications/register', async (req, res) => {
  await notificationClient.registerDevice(req.body);
  res.sendStatus(204);
});

const port = process.env.PORT || 3000;
app.listen(port, () => console.log(`mobile-bff listening on ${port}`));

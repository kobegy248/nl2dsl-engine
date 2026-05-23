import { client } from './client';
import type { FeedbackRequest } from '../types/api';

export const feedbackAPI = {
  submit: (req: FeedbackRequest) =>
    client.post('/api/v1/feedback', req),
};

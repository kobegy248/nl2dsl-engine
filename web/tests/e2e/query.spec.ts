import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const screenshotDir = path.join(__dirname, '../../test-screenshots');

test.describe('查询工作台', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('textarea.ant-input', { timeout: 10000 });
  });

  test.afterEach(async ({ page }, testInfo) => {
    if (!fs.existsSync(screenshotDir)) {
      fs.mkdirSync(screenshotDir, { recursive: true });
    }
    const safeTitle = testInfo.title.replace(/[\\/:*?"<>|]/g, '_');
    const screenshotPath = path.join(screenshotDir, `query-${safeTitle}.png`);
    await page.screenshot({ path: screenshotPath, fullPage: true });
  });

  test('页面标题正确', async ({ page }) => {
    await expect(page).toHaveTitle(/NL2DSL/);
  });

  test('侧边栏导航显示', async ({ page }) => {
    await expect(page.getByRole('menuitem', { name: '查询工作台' })).toBeVisible();
    await expect(page.getByRole('menuitem', { name: '管理后台' })).toBeVisible();
  });

  test('查询输入框存在且可输入', async ({ page }) => {
    const input = page.getByPlaceholder(/输入自然语言查询/);
    await expect(input).toBeVisible();
    await input.fill('查询华东销售额');
    await expect(input).toHaveValue('查询华东销售额');
  });

  test('查询按钮在输入后可用', async ({ page }) => {
    const input = page.getByPlaceholder(/输入自然语言查询/);
    const button = page.getByRole('button', { name: '查询' });

    await expect(button).toBeDisabled();
    await input.fill('测试查询');
    await expect(button).toBeEnabled();
  });

  test('执行查询并展示结果', async ({ page }) => {
    const input = page.getByPlaceholder(/输入自然语言查询/);
    const button = page.getByRole('button', { name: '查询' });

    await input.fill('查询华东销售额');
    await button.click();

    // 等待结果卡片出现
    await page.waitForSelector('.ant-card:has-text("查询结果")', { timeout: 60000 });
    const resultCard = page.locator('.ant-card').filter({ hasText: '查询结果' }).first();
    await expect(resultCard).toBeVisible();
  });

  test('DSL/SQL/执行链路标签页可切换', async ({ page }) => {
    const input = page.getByPlaceholder(/输入自然语言查询/);
    const button = page.getByRole('button', { name: '查询' });

    await input.fill('查询华东销售额');
    await button.click();

    // 等待结果出现
    await page.waitForSelector('.ant-card:has-text("查询结果")', { timeout: 60000 });

    // 切换 SQL 标签
    await page.getByRole('tab', { name: /SQL/ }).click();
    await page.waitForTimeout(500);

    // 如果误触了"查看"按钮导致 SQL 预览模态框打开，先关闭
    await page.locator('.ant-modal-close').first().click({ force: true }).catch(() => {});
    await page.waitForTimeout(300);

    // 切换执行链路标签
    await page.locator('.ant-tabs-tab').filter({ hasText: /执行链路/ }).click();
    await page.waitForTimeout(500);
    // trace 为空数组时 Timeline 不渲染节点，验证标签激活即可
    const traceTab = page.locator('.ant-tabs-tab').filter({ hasText: /执行链路/ });
    await expect(traceTab).toHaveClass(/ant-tabs-tab-active/);
  });

  test('表格/图表视图可切换', async ({ page }) => {
    const input = page.getByPlaceholder(/输入自然语言查询/);
    const button = page.getByRole('button', { name: '查询' });

    await input.fill('查询华东销售额');
    await button.click();

    await page.waitForSelector('.ant-card:has-text("查询结果")', { timeout: 60000 });

    // 切换到柱状图
    await page.getByText('柱状图').click();
    await expect(page.locator('canvas')).toBeVisible();

    // 切换到折线图
    await page.getByText('折线图').click();
    await expect(page.locator('canvas')).toBeVisible();

    // 切换回表格
    await page.getByText('表格').click();
    await expect(page.locator('.ant-table')).toBeVisible();
  });
});

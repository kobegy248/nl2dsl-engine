import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const screenshotDir = path.join(__dirname, '../../test-screenshots');

test.describe('管理后台', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/admin');
    // 等待页面完全加载（React + Ant Design 渲染需要时间）
    await page.waitForTimeout(3000);
  });

  test.afterEach(async ({ page }, testInfo) => {
    if (!fs.existsSync(screenshotDir)) {
      fs.mkdirSync(screenshotDir, { recursive: true });
    }
    const safeTitle = testInfo.title.replace(/[\\/:*?"<>|]/g, '_');
    const screenshotPath = path.join(screenshotDir, `admin-${safeTitle}.png`);
    await page.screenshot({ path: screenshotPath, fullPage: true });
  });

  test('管理后台页面渲染', async ({ page }) => {
    // 使用更宽松的选择器，等待 Ant Design 菜单渲染
    await expect(page.locator('li').filter({ hasText: '指标管理' }).first()).toBeVisible({ timeout: 10000 });
    await expect(page.locator('li').filter({ hasText: '审计日志' }).first()).toBeVisible({ timeout: 10000 });
    await expect(page.locator('li').filter({ hasText: '权限配置' }).first()).toBeVisible({ timeout: 10000 });
  });

  test('指标管理展示指标表格', async ({ page }) => {
    await page.locator('li').filter({ hasText: '指标管理' }).first().click();
    await page.waitForTimeout(2000);

    await expect(page.getByText('指标定义').first()).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('维度定义').first()).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('数据源').first()).toBeVisible({ timeout: 10000 });
  });

  test('审计日志页面展示列表', async ({ page }) => {
    await page.locator('li').filter({ hasText: '审计日志' }).first().click();
    await page.waitForTimeout(2000);

    await expect(page.getByText('时间').first()).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('用户').first()).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('状态').first()).toBeVisible({ timeout: 10000 });
  });

  test('权限配置页面渲染', async ({ page }) => {
    await page.locator('li').filter({ hasText: '权限配置' }).first().click();
    await page.waitForTimeout(500);

    await expect(page.getByText('权限配置').first()).toBeVisible({ timeout: 10000 });
  });

  test('侧边栏可切换到查询工作台', async ({ page }) => {
    await page.getByRole('menuitem', { name: '查询工作台' }).click();
    await page.waitForSelector('textarea.ant-input', { timeout: 10000 });
    await expect(page.getByPlaceholder(/输入自然语言查询/)).toBeVisible();
  });
});

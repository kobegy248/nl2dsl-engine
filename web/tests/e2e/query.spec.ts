import { test, expect } from '@playwright/test';

test.describe('查询工作台', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('页面标题正确', async ({ page }) => {
    await expect(page).toHaveTitle(/NL2DSL/);
  });

  test('侧边栏导航显示', async ({ page }) => {
    await expect(page.getByText('查询工作台')).toBeVisible();
    await expect(page.getByText('管理后台')).toBeVisible();
  });

  test('查询输入框存在且可输入', async ({ page }) => {
    const input = page.locator('textarea');
    await expect(input).toBeVisible();
    await input.fill('查询华东销售额');
    await expect(input).toHaveValue('查询华东销售额');
  });

  test('查询按钮在输入后可用', async ({ page }) => {
    const input = page.locator('textarea');
    const button = page.getByRole('button', { name: '查询' });

    await expect(button).toBeDisabled();
    await input.fill('测试查询');
    await expect(button).toBeEnabled();
  });

  test('执行查询并展示结果', async ({ page }) => {
    const input = page.locator('textarea');
    const button = page.getByRole('button', { name: '查询' });

    await input.fill('查询华东销售额');
    await button.click();

    // 等待加载完成
    await page.waitForTimeout(5000);

    // 检查结果区域出现
    const resultCard = page.locator('.ant-card').filter({ hasText: '查询结果' });
    await expect(resultCard.first()).toBeVisible({ timeout: 15000 });
  });

  test('DSL/SQL/执行链路标签页可切换', async ({ page }) => {
    const input = page.locator('textarea');
    const button = page.getByRole('button', { name: '查询' });

    await input.fill('查询华东销售额');
    await button.click();
    await page.waitForTimeout(5000);

    // 等待结果出现
    await expect(page.locator('.ant-card').filter({ hasText: '查询结果' }).first()).toBeVisible({ timeout: 15000 });

    // 切换 DSL 标签
    await page.getByText('DSL').click();
    await expect(page.locator('pre').filter({ hasText: 'data_source' })).toBeVisible();

    // 切换 SQL 标签
    await page.getByText('SQL').click();
    await expect(page.locator('pre').filter({ hasText: 'SELECT' })).toBeVisible();

    // 切换执行链路标签
    await page.getByText('执行链路').click();
    await expect(page.locator('.ant-timeline')).toBeVisible();
  });

  test('表格/图表视图可切换', async ({ page }) => {
    const input = page.locator('textarea');
    const button = page.getByRole('button', { name: '查询' });

    await input.fill('查询华东销售额');
    await button.click();
    await page.waitForTimeout(5000);

    await expect(page.locator('.ant-card').filter({ hasText: '查询结果' }).first()).toBeVisible({ timeout: 15000 });

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

context("bigartm simple master set up")


test_that("create master", {
  master_conf <- artm_master_conf('.')
  master_id <- artm_create_mater(master_conf)
  expect_gt(master_id, 0)
})

test_that("create dict", {
  master_conf <- artm_master_conf('.')
  master_id <- artm_create_mater(master_conf)
  expect_gt(master_id, 0)

  dict_conf <- artm_dict_conf(tokens = letters,
                              token_counts = seq_along(letters),
                              dict_name = 'dict_1')

  res <- artm_create_dict(master_id, dict_conf)
  expect_equal(res, 0)
})
